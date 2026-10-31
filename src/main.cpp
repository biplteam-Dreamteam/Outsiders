#include <iostream>
#include <string>
#include <vector>
#include <memory>
#include <chrono>

#include "ticket_processor.hpp"
#include "dynamic_batcher.hpp"

// RapidJSON headers
#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#if __has_include(<crow.h>)
#include <crow.h>
#define HAS_CROW 1
#elif __has_include(<crow_all.h>)
#include <crow_all.h>
#define HAS_CROW 1
#else
#define HAS_CROW 0
#endif

using namespace grand_copilot;

int main(int argc, char** argv) {
    std::cout << "==========================================================" << std::endl;
    std::cout << "🚀 Grand Mobile Support Copilot — Native C++20 HFT Server" << std::endl;
    std::cout << "⚡ Engine: Pure C++ Server (Crow Async + ONNX + Dynamic Batcher 3ms)" << std::endl;
    std::cout << "==========================================================" << std::endl;

    std::string rules_file = "rules.json";
    std::string onnx_file = "models/classifier.onnx";
    if (argc > 1) rules_file = argv[1];
    if (argc > 2) onnx_file = argv[2];

    // Initialize core components with 3 ms Smart-Batching
    auto processor = std::make_shared<TicketProcessor>(rules_file, onnx_file);
    auto batcher = std::make_shared<DynamicBatcher>(
        16, // Max Batch Size
        std::chrono::milliseconds(3), // Exact 3 ms Smart-Batching Timeout
        "http://localhost:11434/v1",
        "qwen2.5:3b-instruct-q4_K_M"
    );

#if HAS_CROW
    crow::SimpleApp app;

    // Healthcheck endpoint
    CROW_ROUTE(app, "/health")
    ([]() {
        rapidjson::StringBuffer s;
        rapidjson::Writer<rapidjson::StringBuffer> writer(s);
        writer.StartObject();
        writer.Key("status");
        writer.String("ok");
        writer.Key("engine");
        writer.String("C++20 Native High-Frequency Server");
        writer.Key("architecture");
        writer.String("Crow + ONNX Runtime + Dynamic Batching (3ms)");
        writer.Key("cost_per_ticket");
        writer.String("$0.000");
        writer.EndObject();
        return crow::response(200, s.GetString());
    });

    // High-performance POST /triage
    CROW_ROUTE(app, "/triage").methods(crow::HTTPMethod::POST)
    ([processor, batcher](const crow::request& req) {
        rapidjson::Document doc;
        doc.Parse(req.body.c_str());
        if (doc.HasParseError()) {
            return crow::response(400, "{\"error\":\"Malformed JSON input\"}");
        }

        std::string json_resp = processor->process_ticket_json(doc, batcher.get());
        crow::response resp(200, std::move(json_resp));
        resp.set_header("Content-Type", "application/json; charset=utf-8");
        return resp;
    });

    std::cout << "[INFO] Server listening on port 8000 (Multi-threaded Crow Async, 3ms batching)..." << std::endl;
    app.port(8000).multithreaded().run();
#else
    std::cout << "[INFO] Standalone native C++ engine test mode (Crow not pre-installed on host)." << std::endl;
    std::cout << "[INFO] Testing cp1251 fix: " << TicketProcessor::fix_cp1251("Меніѕ аккаунтымды ўрлап кетті") << std::endl;
    std::cout << "[INFO] Testing language: " << TicketProcessor::detect_language("Менің аккаунтымды ұрлап кетті") << std::endl;
    std::cout << "[INFO] C++ Engine initialized successfully." << std::endl;
#endif

    return 0;
}
