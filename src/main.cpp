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

std::string build_json_response(
    const std::string& lang,
    const std::string& category,
    const std::string& priority,
    bool is_spam,
    const ExtractedFacts& extracted,
    const std::string& draft_text,
    const std::vector<std::string>& cited_rules,
    bool needs_human,
    double confidence,
    const std::vector<std::string>& reasons
) {
    rapidjson::StringBuffer s;
    rapidjson::Writer<rapidjson::StringBuffer> writer(s);

    writer.StartObject();

    writer.Key("lang");
    writer.String(lang.c_str());

    writer.Key("category");
    writer.String(category.c_str());

    writer.Key("priority");
    writer.String(priority.c_str());

    writer.Key("is_spam_or_duplicate");
    writer.Bool(is_spam);

    writer.Key("extracted");
    writer.StartObject();
    writer.Key("nickname");
    if (extracted.nickname.empty()) writer.Null();
    else writer.String(extracted.nickname.c_str());

    writer.Key("rule_refs");
    writer.StartArray();
    for (const auto& r : extracted.rule_refs) writer.String(r.c_str());
    writer.EndArray();

    writer.Key("has_evidence");
    writer.Bool(extracted.has_evidence);

    writer.Key("server");
    if (extracted.server.empty()) writer.Null();
    else writer.String(extracted.server.c_str());
    writer.EndObject();

    writer.Key("draft_reply");
    writer.StartObject();
    writer.Key("lang");
    writer.String(lang.c_str());
    writer.Key("text");
    writer.String(draft_text.c_str());
    writer.Key("cited");
    writer.StartArray();
    for (const auto& c : cited_rules) writer.String(c.c_str());
    writer.EndArray();
    writer.EndObject();

    writer.Key("needs_human");
    writer.Bool(needs_human);

    writer.Key("confidence");
    writer.Double(confidence);

    writer.Key("reasons");
    writer.StartArray();
    for (const auto& r : reasons) writer.String(r.c_str());
    writer.EndArray();

    writer.EndObject();

    return s.GetString();
}

int main(int argc, char** argv) {
    std::cout << "==========================================================" << std::endl;
    std::cout << "🚀 Grand Mobile Support Copilot — Native C++20 HFT Server" << std::endl;
    std::cout << "⚡ Engine: Pure C++ Server (Crow Async + ONNX + Dynamic Batcher)" << std::endl;
    std::cout << "==========================================================" << std::endl;

    std::string rules_file = "rules.json";
    std::string onnx_file = "models/classifier.onnx";
    if (argc > 1) rules_file = argv[1];
    if (argc > 2) onnx_file = argv[2];

    // Initialize core components
    auto processor = std::make_shared<TicketProcessor>(rules_file, onnx_file);
    auto batcher = std::make_shared<DynamicBatcher>(
        16, // Max Batch Size
        std::chrono::milliseconds(20), // 20ms dynamic batching window
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
        writer.String("Crow + ONNX Runtime + Dynamic Batching");
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

        // 1. Extract messages
        std::string raw_text;
        if (doc.HasMember("messages") && doc["messages"].IsArray()) {
            const auto& msgs = doc["messages"];
            for (rapidjson::SizeType i = 0; i < msgs.Size(); ++i) {
                const auto& m = msgs[i];
                if (m.HasMember("role") && m["role"].IsString() && std::string(m["role"].GetString()) == "player") {
                    if (m.HasMember("text") && m["text"].IsString()) {
                        raw_text += m["text"].GetString();
                        raw_text += " ";
                    }
                }
            }
        }

        std::string clean_text = TicketProcessor::fix_cp1251(raw_text);

        // 2. Language Detection
        std::string def_lang = "ru";
        if (doc.HasMember("lang") && doc["lang"].IsString()) def_lang = doc["lang"].GetString();
        else if (doc.HasMember("server_lang") && doc["server_lang"].IsString()) def_lang = doc["server_lang"].GetString();
        std::string lang = TicketProcessor::detect_language(clean_text, def_lang);

        // 3. Facts Extraction
        std::string raw_refs = doc.HasMember("rule_refs_raw") && doc["rule_refs_raw"].IsString() 
            ? doc["rule_refs_raw"].GetString() : "";
        int img_cnt = doc.HasMember("images_count") && doc["images_count"].IsInt() 
            ? doc["images_count"].GetInt() : 0;
        std::string rep_nick = doc.HasMember("reported_nick") && doc["reported_nick"].IsString() 
            ? doc["reported_nick"].GetString() : "";
        std::string srv_str = doc.HasMember("region") && doc["region"].IsString() 
            ? doc["region"].GetString() : "";

        ExtractedFacts facts = TicketProcessor::extract_facts(clean_text, raw_refs, img_cnt, rep_nick, srv_str);

        // 4. Kind
        std::string kind = doc.HasMember("kind") && doc["kind"].IsString() 
            ? doc["kind"].GetString() : "complaint";

        // 5. Classification
        ClassificationResult cls = processor->classify_ticket(clean_text, kind, facts.has_evidence);

        // 6. Guardrails
        GuardrailResult guard = TicketProcessor::check_guardrails(clean_text, kind, cls.category, facts.has_evidence);
        bool needs_human = guard.needs_human || cls.low_confidence_needs_human;
        std::vector<std::string> reasons = guard.reasons;
        if (cls.low_confidence_needs_human) {
            reasons.push_back("Низкая уверенность классификатора (confidence < 0.55)");
        }

        // 7. RAG Search
        std::vector<std::string> matched_rules = processor->get_rule_db().search(clean_text, cls.category, 4);

        // 8. Generate Draft via Dynamic Batcher or Instant Fallback
        std::string fallback_draft = processor->generate_fallback_draft(lang, cls.category, facts.nickname, matched_rules);
        std::string final_draft_text;

        if (needs_human) {
            // Instant return for high-risk / guardrail tickets (< 0.5 ms)
            final_draft_text = fallback_draft;
        } else {
            // Queue into Dynamic Batcher for batched LLM synthesis
            auto task = std::make_shared<TriageTask>();
            task->ticket_id = doc.HasMember("ticket_id") && doc["ticket_id"].IsString() ? doc["ticket_id"].GetString() : "";
            task->lang = lang;
            task->query = clean_text;
            task->category = cls.category;
            task->nickname = facts.nickname;
            task->rules = matched_rules;
            task->fallback_reply = fallback_draft;

            std::future<std::string> reply_future = batcher->enqueue(task);
            final_draft_text = reply_future.get();
        }

        std::string json_resp = build_json_response(
            lang,
            cls.category,
            cls.priority,
            false,
            facts,
            final_draft_text,
            matched_rules,
            needs_human,
            cls.confidence,
            reasons
        );

        crow::response resp(200, json_resp);
        resp.set_header("Content-Type", "application/json; charset=utf-8");
        return resp;
    });

    std::cout << "[INFO] Server listening on port 8000 (Multi-threaded Crow Async)..." << std::endl;
    app.port(8000).multithreaded().run();
#else
    std::cout << "[INFO] Standalone native C++ engine test mode (Crow not pre-installed on host)." << std::endl;
    std::cout << "[INFO] Testing cp1251 fix: " << TicketProcessor::fix_cp1251("Меніѕ аккаунтымды ўрлап кетті") << std::endl;
    std::cout << "[INFO] Testing language: " << TicketProcessor::detect_language("Менің аккаунтымды ұрлап кетті") << std::endl;
    std::cout << "[INFO] C++ Engine initialized successfully." << std::endl;
#endif

    return 0;
}
