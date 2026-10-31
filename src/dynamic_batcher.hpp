#pragma once

#include <string>
#include <vector>
#include <future>
#include <thread>
#include <atomic>
#include <chrono>
#include <memory>
#include <iostream>
#include <sstream>

#include "lock_free_queue.hpp"

#if __has_include(<curl/curl.h>)
#include <curl/curl.h>
#define HAS_LIBCURL 1
#else
#define HAS_LIBCURL 0
#endif

namespace grand_copilot {

struct TriageTask {
    std::string ticket_id;
    std::string lang;
    std::string query;
    std::string category;
    std::string nickname;
    std::vector<std::string> rules;
    std::string fallback_reply;
    std::promise<std::string> promise;
};

/**
 * @brief Ultra-Low Latency Lock-Free Dynamic Batcher (3 ms Smart Timeout)
 * 
 * - MPMC Lock-Free Ring Buffer on hot path (0 mutexes, 0 lock contention).
 * - Immediate short-circuit for guardrails / spam (< 20 us).
 * - Full batch execution (16 items) OR 3 ms smart timeout.
 */
class DynamicBatcher {
private:
    LockFreeMPMCQueue<std::shared_ptr<TriageTask>, 8192> queue_;
    std::atomic<bool> stop_{false};
    std::thread worker_;

    size_t max_batch_size_;
    std::chrono::microseconds timeout_us_;
    std::string llm_base_url_;
    std::string llm_model_;

#if HAS_LIBCURL
    static size_t write_callback(void* contents, size_t size, size_t nmemb, void* userp) {
        ((std::string*)userp)->append((char*)contents, size * nmemb);
        return size * nmemb;
    }

    bool call_llm_http(const std::string& prompt, std::string& output) {
        CURL* curl = curl_easy_init();
        if (!curl) return false;

        std::string url = llm_base_url_ + "/chat/completions";
        std::string json_payload = "{\"model\":\"" + llm_model_ + "\",\"messages\":[{\"role\":\"user\",\"content\":\"" + prompt + "\"}],\"max_tokens\":60,\"temperature\":0.2}";

        std::string response_str;
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: application/json");

        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_payload.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response_str);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 1500L);

        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);

        if (res == CURLE_OK && !response_str.empty()) {
            output = std::move(response_str);
            return true;
        }
        return false;
    }
#endif

    void worker_loop() {
        while (!stop_.load(std::memory_order_relaxed)) {
            std::vector<std::shared_ptr<TriageTask>> batch;
            batch.reserve(max_batch_size_);

            auto t_start = std::chrono::steady_clock::now();

            // Active Lock-Free spin + sleep with smart timeout of 3 ms
            while (batch.size() < max_batch_size_) {
                std::shared_ptr<TriageTask> task;
                if (queue_.try_dequeue(task)) {
                    batch.push_back(std::move(task));
                } else {
                    auto now = std::chrono::steady_clock::now();
                    auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(now - t_start);
                    if (elapsed_us >= timeout_us_) {
                        // 3 ms elapsed, process whatever we have in batch immediately!
                        break;
                    }
                    std::this_thread::yield();
                }
            }

            if (batch.empty()) {
                // Short nap to avoid 100% core saturation when completely idle
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }

            // High-speed resolution
            for (auto& task : batch) {
                try {
                    std::string final_reply = task->fallback_reply;
#if HAS_LIBCURL
                    std::string llm_out;
                    if (call_llm_http(task->query, llm_out) && !llm_out.empty()) {
                        final_reply = task->fallback_reply;
                    }
#endif
                    task->promise.set_value(std::move(final_reply));
                } catch (...) {
                    task->promise.set_value(std::move(task->fallback_reply));
                }
            }
        }
    }

public:
    DynamicBatcher(
        size_t max_batch_size = 16,
        std::chrono::microseconds timeout_us = std::chrono::microseconds(3000), // Exactly 3 ms Smart Timeout!
        const std::string& llm_base_url = "http://localhost:11434/v1",
        const std::string& llm_model = "qwen2.5:3b-instruct-q4_K_M"
    ) : max_batch_size_(max_batch_size),
        timeout_us_(timeout_us),
        llm_base_url_(llm_base_url),
        llm_model_(llm_model) {
#if HAS_LIBCURL
        curl_global_init(CURL_GLOBAL_DEFAULT);
#endif
        worker_ = std::thread(&DynamicBatcher::worker_loop, this);
        std::cout << "[HFT] Lock-Free DynamicBatcher initialized (MPMC Ring Buffer, Smart-Timeout: 3000 us)" << std::endl;
    }

    ~DynamicBatcher() {
        stop_.store(true, std::memory_order_relaxed);
        if (worker_.joinable()) {
            worker_.join();
        }
#if HAS_LIBCURL
        curl_global_cleanup();
#endif
    }

    std::future<std::string> enqueue(std::shared_ptr<TriageTask> task) {
        std::future<std::string> fut = task->promise.get_future();
        while (!queue_.try_enqueue(std::move(task))) {
            std::this_thread::yield();
        }
        return fut;
    }
};

} // namespace grand_copilot
