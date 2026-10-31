#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>
#include <string_view>
#include <chrono>

namespace grand_copilot {

/**
 * @brief High-Performance Lock-Free Multi-Producer Multi-Consumer (MPMC) Ring Buffer.
 * 
 * Based on Dmitry Vyukov's bounded MPMC queue algorithm:
 * - Cache-line aligned (alignas(64)) to eliminate false sharing.
 * - Zero mutexes, zero kernel transitions on hot path.
 * - std::memory_order_acquire / std::memory_order_release semantics.
 */
template <typename T, size_t Capacity = 4096>
class LockFreeMPMCQueue {
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be a power of 2");

    struct Node {
        std::atomic<size_t> sequence;
        T data;
    };

    alignas(64) Node buffer_[Capacity];
    static constexpr size_t BufferMask = Capacity - 1;

    alignas(64) std::atomic<size_t> enqueue_pos_{0};
    alignas(64) std::atomic<size_t> dequeue_pos_{0};

public:
    LockFreeMPMCQueue() {
        for (size_t i = 0; i < Capacity; ++i) {
            buffer_[i].sequence.store(i, std::memory_order_relaxed);
        }
    }

    ~LockFreeMPMCQueue() = default;

    // Non-copyable, non-movable
    LockFreeMPMCQueue(const LockFreeMPMCQueue&) = delete;
    LockFreeMPMCQueue& operator=(const LockFreeMPMCQueue&) = delete;

    bool try_enqueue(T&& data) {
        Node* node;
        size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
        for (;;) {
            node = &buffer_[pos & BufferMask];
            size_t seq = node->sequence.load(std::memory_order_acquire);
            intptr_t diff = (intptr_t)seq - (intptr_t)pos;
            if (diff == 0) {
                if (enqueue_pos_.compare_exchange_weak(pos, pos + 1, std::memory_order_relaxed)) {
                    break;
                }
            } else if (diff < 0) {
                // Queue is full
                return false;
            } else {
                pos = enqueue_pos_.load(std::memory_order_relaxed);
            }
        }

        node->data = std::move(data);
        node->sequence.store(pos + 1, std::memory_order_release);
        return true;
    }

    bool try_dequeue(T& result) {
        Node* node;
        size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
        for (;;) {
            node = &buffer_[pos & BufferMask];
            size_t seq = node->sequence.load(std::memory_order_acquire);
            intptr_t diff = (intptr_t)seq - (intptr_t)(pos + 1);
            if (diff == 0) {
                if (dequeue_pos_.compare_exchange_weak(pos, pos + 1, std::memory_order_relaxed)) {
                    break;
                }
            } else if (diff < 0) {
                // Queue is empty
                return false;
            } else {
                pos = dequeue_pos_.load(std::memory_order_relaxed);
            }
        }

        result = std::move(node->data);
        node->sequence.store(pos + BufferMask + 1, std::memory_order_release);
        return true;
    }

    size_t approximate_size() const {
        size_t enq = enqueue_pos_.load(std::memory_order_relaxed);
        size_t deq = dequeue_pos_.load(std::memory_order_relaxed);
        return (enq >= deq) ? (enq - deq) : 0;
    }

    bool empty() const {
        return approximate_size() == 0;
    }
};

/**
 * @brief Lock-Free High-Throughput Deduplicator and Anti-Spam Table.
 * 
 * - Open-addressing hash table with atomic CAS slots.
 * - Eliminates locks under massive concurrency (e.g., 64 threads hammering 10,000 DDoS tickets).
 * - Tracks 1-hour sliding window per reporter_hash.
 * - Flags as spam if ticket count >= 5 within 3600 seconds.
 */
class LockFreeDeduplicator {
public:
    static constexpr size_t TABLE_SIZE = 16384; // Power of 2
    static constexpr size_t TABLE_MASK = TABLE_SIZE - 1;
    static constexpr uint64_t WINDOW_SECONDS = 3600; // 1 hour sliding window
    static constexpr uint32_t SPAM_THRESHOLD = 5;

    struct alignas(32) Slot {
        std::atomic<uint64_t> reporter_hash{0};
        std::atomic<uint64_t> window_start_sec{0};
        std::atomic<uint32_t> count{0};
        uint8_t padding[12]; // Keep aligned to cache lines
    };

private:
    Slot table_[TABLE_SIZE];

    static uint64_t hash_str(std::string_view s) {
        // High-speed 64-bit FNV-1a hash
        uint64_t h = 14695981039346656037ULL;
        for (char c : s) {
            h ^= static_cast<uint8_t>(c);
            h *= 1099511628211ULL;
        }
        return (h == 0) ? 1 : h; // 0 reserved for empty slot
    }

public:
    LockFreeDeduplicator() = default;

    /**
     * @brief Atomically checks and updates ticket submission frequency.
     * @param reporter_str reporter hash or identifier
     * @return true if detected as duplicate or spam (>= 5 tickets/hour), false otherwise.
     */
    bool check_and_update(std::string_view reporter_str) {
        if (reporter_str.empty()) return false;

        uint64_t r_hash = hash_str(reporter_str);
        uint64_t now_sec = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now().time_since_epoch()
            ).count()
        );

        size_t idx = r_hash & TABLE_MASK;

        // Linear probing across atomic slots
        for (size_t probe = 0; probe < 32; ++probe) {
            Slot& slot = table_[(idx + probe) & TABLE_MASK];
            uint64_t existing_hash = slot.reporter_hash.load(std::memory_order_acquire);

            // Attempt to claim empty slot
            if (existing_hash == 0) {
                uint64_t expected = 0;
                if (slot.reporter_hash.compare_exchange_strong(expected, r_hash, std::memory_order_acq_rel)) {
                    slot.window_start_sec.store(now_sec, std::memory_order_relaxed);
                    slot.count.store(1, std::memory_order_release);
                    return false;
                }
                existing_hash = expected;
            }

            // Matching existing reporter
            if (existing_hash == r_hash) {
                uint64_t win_start = slot.window_start_sec.load(std::memory_order_relaxed);
                if (now_sec - win_start > WINDOW_SECONDS) {
                    // Window expired, reset atomically
                    slot.window_start_sec.store(now_sec, std::memory_order_relaxed);
                    slot.count.store(1, std::memory_order_release);
                    return false;
                }

                // Increment submission count
                uint32_t current_count = slot.count.fetch_add(1, std::memory_order_acq_rel) + 1;
                return current_count >= SPAM_THRESHOLD;
            }
        }

        return false;
    }
};

} // namespace grand_copilot
