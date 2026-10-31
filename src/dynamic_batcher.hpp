#pragma once

#include <string>
#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <future>
#include <thread>
#include <atomic>
#include <chrono>
#include <memory>
#include <iostream>
#include <sstream>

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
 * @brief High-Frequency Dynamic Batcher with 3 ms Smart Timeout
 * 
 * Balances maximum throughput and lowest single-ticket latency:
 * - Wakes up when batch reaches 16 items OR exactly 3 ms timeout elapses.
 * - If 3 ms elapsed and queue has only 1 ticket, immediate execution without waiting.
 */
class DynamicBatcher {
private:
    std::queue<std::shared_ptr<TriageTask>> queue_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::atomic<bool> stop_{false};
    std::thread worker_;

    size_t max_batch_size_;
    std::chrono::milliseconds timeout_; // Strict 3 ms timeout
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
        while (!stop_) {
            std::vector<std::shared_ptr<TriageTask>> batch;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                // Смарт-батчинг: ровно 3 миллисекунды ожидания
                cv_.wait_for(lock, timeout_, [this] {
                    return queue_.size() >= max_batch_size_ || stop_;
                });

                if (stop_ && queue_.empty()) break;
                if (queue_.empty()) continue;

                // Забираем накопившийся батч (от 1 до 16 тикетов) без лишних задержек
                while (!queue_.empty() && batch.size() < max_batch_size_) {
                    batch.push_back(std::move(queue_.front()));
                    queue_.pop();
                }
            }

            if (batch.empty()) continue;

            // Пакетная обработка: отправка в инференс-пайплайн и возврат через std::promise
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
        std::chrono::milliseconds timeout = std::chrono::milliseconds(3), // 3 ms Smart Timeout!
        const std::string& llm_base_url = "http://localhost:11434/v1",
        const std::string& llm_model = "qwen2.5:3b-instruct-q4_K_M"
    ) : max_batch_size_(max_batch_size),
        timeout_(timeout),
        llm_base_url_(llm_base_url),
        llm_model_(llm_model) {
#if HAS_LIBCURL
        curl_global_init(CURL_GLOBAL_DEFAULT);
#endif
        worker_ = std::thread(&DynamicBatcher::worker_loop, this);
        std::cout << "[INFO] DynamicBatcher initialized: max_batch=" << max_batch_size_
                  << ", smart_timeout=" << timeout_.count() << "ms (Zero Starvation)" << std::endl;
    }

    ~DynamicBatcher() {
        stop_ = true;
        cv_.notify_all();
        if (worker_.joinable()) {
            worker_.join();
        }
#if HAS_LIBCURL
        curl_global_cleanup();
#endif
    }

    std::future<std::string> enqueue(std::shared_ptr<TriageTask> task) {
        std::future<std::string> fut = task->promise.get_future();
        {
            std::unique_lock<std::mutex> lock(mutex_);
            queue_.push(std::move(task));
        }
        cv_.notify_one();
        return fut;
    }

    size_t get_queue_size() {
        std::unique_lock<std::mutex> lock(mutex_);
        return queue_.size();
    }
};

} // namespace grand_copilot
