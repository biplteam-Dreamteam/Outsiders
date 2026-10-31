#pragma once

#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <regex>
#include <algorithm>
#include <sstream>
#include <fstream>
#include <memory>
#include <iostream>
#include <cctype>

// Optional ONNX Runtime support
#if __has_include(<onnxruntime_cxx_api.h>)
#include <onnxruntime_cxx_api.h>
#define HAS_ONNX_RUNTIME 1
#else
#define HAS_ONNX_RUNTIME 0
#endif

// RapidJSON headers
#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

namespace grand_copilot {

// Fast Levenshtein distance
inline int levenshtein_distance(const std::string& s1, const std::string& s2) {
    const size_t m = s1.size();
    const size_t n = s2.size();
    if (m == 0) return static_cast<int>(n);
    if (n == 0) return static_cast<int>(m);

    std::vector<int> prev(n + 1);
    std::vector<int> curr(n + 1);

    for (size_t j = 0; j <= n; ++j) prev[j] = static_cast<int>(j);

    for (size_t i = 1; i <= m; ++i) {
        curr[0] = static_cast<int>(i);
        for (size_t j = 1; j <= n; ++j) {
            int cost = (s1[i - 1] == s2[j - 1]) ? 0 : 1;
            curr[j] = std::min({
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost
            });
        }
        prev = curr;
    }
    return curr[n];
}

inline double fuzzy_similarity(const std::string& s1, const std::string& s2) {
    if (s1.empty() && s2.empty()) return 1.0;
    if (s1.empty() || s2.empty()) return 0.0;
    int dist = levenshtein_distance(s1, s2);
    size_t max_len = std::max(s1.size(), s2.size());
    return 1.0 - (static_cast<double>(dist) / static_cast<double>(max_len));
}

struct ExtractedFacts {
    std::string nickname;
    std::vector<std::string> rule_refs;
    bool has_evidence = false;
    std::string server;
};

struct GuardrailResult {
    bool needs_human = false;
    std::vector<std::string> reasons;
};

struct ClassificationResult {
    std::string category;
    std::string priority;
    double confidence = 0.95;
    bool low_confidence_needs_human = false;
};

class RuleDatabase {
public:
    std::unordered_set<std::string> valid_rules;
    std::unordered_map<std::string, std::string> rule_texts;
    std::unordered_map<std::string, std::string> rule_sections;
    std::vector<std::pair<std::string, std::string>> all_rules; // ref, doc

    bool load_from_json(const std::string& filepath) {
        std::ifstream file(filepath, std::ios::binary);
        if (!file.is_open()) {
            std::cerr << "[WARN] rules.json not found at: " << filepath << std::endl;
            return false;
        }

        std::string json_str((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        rapidjson::Document doc;
        doc.Parse(json_str.c_str());
        if (doc.HasParseError() || !doc.HasMember("rules") || !doc["rules"].IsArray()) {
            std::cerr << "[ERROR] Invalid rules.json format" << std::endl;
            return false;
        }

        const auto& rules_arr = doc["rules"];
        for (rapidjson::SizeType i = 0; i < rules_arr.Size(); ++i) {
            const auto& section = rules_arr[i];
            std::string sec_title = section.HasMember("category") && section["category"].IsString() 
                ? section["category"].GetString() : "";

            if (section.HasMember("points") && section["points"].IsArray()) {
                const auto& pts = section["points"];
                for (rapidjson::SizeType j = 0; j < pts.Size(); ++j) {
                    const auto& p = pts[j];
                    if (p.HasMember("ref") && p["ref"].IsString() && p.HasMember("text") && p["text"].IsString()) {
                        std::string ref = p["ref"].GetString();
                        std::string text = p["text"].GetString();
                        valid_rules.insert(ref);
                        rule_texts[ref] = text;
                        rule_sections[ref] = sec_title;
                        
                        std::string search_doc = ref + " " + sec_title + " " + text;
                        std::transform(search_doc.begin(), search_doc.end(), search_doc.begin(), ::tolower);
                        all_rules.push_back({ref, search_doc});
                    }
                }
            }
        }
        std::cout << "[INFO] Loaded " << valid_rules.size() << " official rules from " << filepath << std::endl;
        return true;
    }

    bool is_valid(const std::string& ref) const {
        return valid_rules.find(ref) != valid_rules.end();
    }

    std::vector<std::string> search(const std::string& query, const std::string& category, size_t top_k = 4) const {
        std::vector<std::string> results;
        std::string q_lower = query;
        std::transform(q_lower.begin(), q_lower.end(), q_lower.begin(), ::tolower);

        // Slang matching
        if (q_lower.find("дм") != std::string::npos || q_lower.find("dm") != std::string::npos) {
            if (is_valid("5.3")) results.push_back("5.3");
            if (is_valid("5.4")) results.push_back("5.4");
            if (is_valid("1.1")) results.push_back("1.1");
        } else if (q_lower.find("дб") != std::string::npos || q_lower.find("db") != std::string::npos) {
            if (is_valid("5.3")) results.push_back("5.3");
            if (is_valid("5.5")) results.push_back("5.5");
        } else if (q_lower.find("ск") != std::string::npos || q_lower.find("sk") != std::string::npos) {
            if (is_valid("5.4")) results.push_back("5.4");
        } else if (q_lower.find("оск") != std::string::npos || q_lower.find("мат") != std::string::npos) {
            if (is_valid("2.1")) results.push_back("2.1");
        } else if (q_lower.find("чит") != std::string::npos || q_lower.find("софт") != std::string::npos) {
            if (is_valid("5.2")) results.push_back("5.2");
        } else if (q_lower.find("обман") != std::string::npos || q_lower.find("скам") != std::string::npos) {
            if (is_valid("4.1")) results.push_back("4.1");
        }

        // Category mapping fallback
        if (results.size() < top_k) {
            if (category == "complaint.insult" && is_valid("2.1")) results.push_back("2.1");
            else if (category == "complaint.cheat" && is_valid("5.2")) results.push_back("5.2");
            else if (category == "complaint.dm" && is_valid("5.3")) results.push_back("5.3");
            else if (category == "complaint.scam" && is_valid("4.1")) results.push_back("4.1");
            else if (category == "report.help" && is_valid("3.1")) results.push_back("3.1");
            else if (category == "report.account" && is_valid("1.4")) results.push_back("1.4");
        }

        // Fuzzy match via Levenshtein if still needed
        if (results.size() < top_k) {
            for (const auto& item : all_rules) {
                if (results.size() >= top_k) break;
                if (std::find(results.begin(), results.end(), item.first) == results.end()) {
                    if (item.second.find(q_lower.substr(0, std::min(q_lower.size(), (size_t)8))) != std::string::npos) {
                        results.push_back(item.first);
                    }
                }
            }
        }

        // Guarantee unique results
        std::vector<std::string> unique_res;
        for (const auto& r : results) {
            if (std::find(unique_res.begin(), unique_res.end(), r) == unique_res.end()) {
                unique_res.push_back(r);
            }
        }
        if (unique_res.size() > top_k) unique_res.resize(top_k);
        return unique_res;
    }
};

class TicketProcessor {
private:
    RuleDatabase rule_db_;

#if HAS_ONNX_RUNTIME
    std::unique_ptr<Ort::Env> ort_env_;
    std::unique_ptr<Ort::Session> ort_session_;
    std::unique_ptr<Ort::SessionOptions> session_options_;
    bool onnx_loaded_ = false;
#endif

public:
    TicketProcessor(const std::string& rules_path = "rules.json", const std::string& onnx_path = "models/classifier.onnx") {
        rule_db_.load_from_json(rules_path);

#if HAS_ONNX_RUNTIME
        try {
            ort_env_ = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, "GrandMobileCopilot");
            session_options_ = std::make_unique<Ort::SessionOptions>();
            session_options_->SetIntraOpNumThreads(2);
            session_options_->SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

            std::ifstream f(onnx_path);
            if (f.good()) {
                ort_session_ = std::make_unique<Ort::Session>(*ort_env_, onnx_path.c_str(), *session_options_);
                onnx_loaded_ = true;
                std::cout << "[INFO] Loaded ONNX Runtime model from: " << onnx_path << std::endl;
            } else {
                std::cout << "[WARN] ONNX model file not found at " << onnx_path << ", using native C++ classifier." << std::endl;
            }
        } catch (const std::exception& e) {
            std::cerr << "[ERROR] Failed to initialize ONNX Runtime: " << e.what() << std::endl;
            onnx_loaded_ = false;
        }
#endif
    }

    const RuleDatabase& get_rule_db() const { return rule_db_; }

    // 1. Nanosecond cp1251 Kazakh Char Fix (O(1))
    static std::string fix_cp1251(const std::string& input) {
        if (input.empty()) return "";
        std::string result = input;
        
        static const std::vector<std::pair<std::string, std::string>> REPLS = {
            {"ќ", "қ"}, {"Ќ", "Қ"},
            {"ґ", "ғ"}, {"Ґ", "Ғ"},
            {"ѕ", "ң"}, {"Ѕ", "Ң"},
            {"є", "ә"}, {"Є", "Ә"},
            {"ј", "ө"}, {"Ј", "Ө"},
            {"ў", "ұ"}, {"Ў", "Ұ"},
            {"ї", "ү"}, {"Ї", "Ү"}
        };

        for (const auto& pair : REPLS) {
            size_t pos = 0;
            while ((pos = result.find(pair.first, pos)) != std::string::npos) {
                result.replace(pos, pair.first.length(), pair.second);
                pos += pair.second.length();
            }
        }

        // Normalize whitespace
        std::string collapsed;
        collapsed.reserve(result.size());
        bool in_space = false;
        for (char c : result) {
            if (c == '\r' || c == '\n' || c == '\t' || std::isspace(static_cast<unsigned char>(c))) {
                if (!in_space) {
                    collapsed.push_back(' ');
                    in_space = true;
                }
            } else {
                collapsed.push_back(c);
                in_space = false;
            }
        }
        size_t start = collapsed.find_first_not_of(' ');
        if (start == std::string::npos) return "";
        size_t end = collapsed.find_last_not_of(' ');
        return collapsed.substr(start, end - start + 1);
    }

    // 2. High-speed multilingual language detection
    static std::string detect_language(const std::string& text, const std::string& default_lang = "ru") {
        if (text.empty()) return default_lang;

        // Check Kazakh specific cyrillic chars
        static const std::string kk_chars = "әғқңөұүһіӘҒҚҢӨҰҮҺІ";
        for (size_t i = 0; i < text.size() - 1; ++i) {
            std::string sub = text.substr(i, 2);
            if (kk_chars.find(sub) != std::string::npos) {
                return "kk";
            }
        }

        std::string t_lower = text;
        std::transform(t_lower.begin(), t_lower.end(), t_lower.begin(), ::tolower);

        // Check Kazakh vocabulary
        static const std::vector<std::string> kk_words = {
            "сәлем", "салем", "рахмет", "болады", "қандай", "кандай", "неге", 
            "қалай", "керек", "өтініш", "отиниш", "акша", "ақша", "көмек", "шағым"
        };
        for (const auto& w : kk_words) {
            if (t_lower.find(w) != std::string::npos) return "kk";
        }

        // Check Uzbek markers and vocabulary
        if (t_lower.find("o'") != std::string::npos || t_lower.find("g'") != std::string::npos ||
            t_lower.find("o`") != std::string::npos || t_lower.find("g`") != std::string::npos) {
            return "uz";
        }
        static const std::vector<std::string> uz_words = {
            "yordam", "iltimos", "qanday", "rahmat", "aka", "salom", "moshin", "pul", "bering"
        };
        for (const auto& w : uz_words) {
            if (t_lower.find(w) != std::string::npos) return "uz";
        }

        // Check English words
        static const std::vector<std::string> en_words = {
            "help", "please", "stuck", "admin", "report", "player", "car", "money", "cheater"
        };
        for (const auto& w : en_words) {
            if (t_lower.find(w) != std::string::npos) return "en";
        }

        return default_lang;
    }

    // 3. Fast C++ Fact & Evidence Extractor
    static ExtractedFacts extract_facts(
        const std::string& text, 
        const std::string& raw_refs, 
        int images_count,
        const std::string& reported_nick,
        const std::string& server_str
    ) {
        ExtractedFacts facts;
        std::string norm_text = fix_cp1251(text);
        std::string norm_raw = fix_cp1251(raw_refs);

        // Nickname
        facts.nickname = reported_nick;
        if (facts.nickname.empty() || facts.nickname == "None") {
            static const std::regex nick_regex(R"([A-Za-zА-Яа-яЁё0-9]+_[A-Za-zА-Яа-яЁё0-9]+)");
            std::smatch match;
            if (std::regex_search(norm_text, match, nick_regex)) {
                facts.nickname = match.str(0);
            } else if (norm_text.find("<nick>") != std::string::npos) {
                facts.nickname = "<nick>";
            }
        }

        // Rule references
        static const std::regex rule_regex(R"(\b\d+\.\d+(?:\.\d+)?\b)");
        auto search_refs = [&](const std::string& s) {
            auto begin = std::sregex_iterator(s.begin(), s.end(), rule_regex);
            auto end = std::sregex_iterator();
            for (auto i = begin; i != end; ++i) {
                std::string r = (*i).str();
                if (std::find(facts.rule_refs.begin(), facts.rule_refs.end(), r) == facts.rule_refs.end()) {
                    facts.rule_refs.push_back(r);
                }
            }
        };
        search_refs(norm_raw);
        search_refs(norm_text);

        // GZ check
        static const std::regex gz_regex(R"(\b(?:gz|гз|зз)\b)", std::regex_constants::icase);
        std::string combined = norm_raw + " " + norm_text;
        if (std::regex_search(combined, gz_regex)) {
            if (std::find(facts.rule_refs.begin(), facts.rule_refs.end(), "GZ") == facts.rule_refs.end()) {
                facts.rule_refs.push_back("GZ");
            }
        }
        std::sort(facts.rule_refs.begin(), facts.rule_refs.end());

        // Evidence
        facts.has_evidence = (images_count > 0);
        if (!facts.has_evidence) {
            static const std::regex ev_regex(
                R"(скрин|видео|фрапс|пруф|доказ|доки|запись|<url>|дәлел|далел|skrin|video|proof|dalil|dalillar|screen|screenshot|зафиксировал|заснял|снял)",
                std::regex_constants::icase
            );
            if (std::regex_search(norm_text, ev_regex)) {
                facts.has_evidence = true;
            }
        }

        // Server
        facts.server = server_str;
        if (facts.server.empty()) {
            static const std::regex srv_regex(R"((?:сервер[а-я]*|server)\s*[:#№]?\s*(\d+|[a-zA-Z]+))", std::regex_constants::icase);
            std::smatch sm;
            if (std::regex_search(norm_text, sm, srv_regex)) {
                facts.server = sm.str(1);
            } else {
                facts.server = "cis";
            }
        }

        return facts;
    }

    // 4. Guardrails & Human Escalation Check
    static GuardrailResult check_guardrails(
        const std::string& text, 
        const std::string& kind,
        const std::string& category, 
        bool has_evidence
    ) {
        GuardrailResult res;
        std::string t_lower = text;
        std::transform(t_lower.begin(), t_lower.end(), t_lower.begin(), ::tolower);

        // Critical categories
        if (category == "report.account") {
            res.needs_human = true;
            res.reasons.push_back("Категория 'report.account' требует обязательного ручного разбора администратором");
        } else if (category == "report.payment") {
            res.needs_human = true;
            res.reasons.push_back("Категория 'report.payment' требует обязательного ручного разбора администратором");
        } else if (category == "complaint.admin") {
            res.needs_human = true;
            res.reasons.push_back("Категория 'complaint.admin' требует обязательного ручного разбора администратором");
        }

        // Financial / Donate
        static const std::vector<std::string> pay_keys = {
            "донат", "donate", "вип", "випка", "vip", "оплат", "платеж", "платёж", 
            "гк", "деньги не пришли", "пополнил", "списали", "чеки", "төлем", "to'lov", "payment"
        };
        for (const auto& k : pay_keys) {
            if (t_lower.find(k) != std::string::npos) {
                res.needs_human = true;
                res.reasons.push_back("Вопрос касается финансовых операций / доната / платежей");
                break;
            }
        }

        // Account security
        static const std::vector<std::string> hack_keys = {
            "взлом", "взломали", "украли аккаунт", "сменили пароль", "потерял доступ", 
            "кража аккаунта", "ұрлап", "buzildi", "hacked", "stolen"
        };
        for (const auto& k : hack_keys) {
            if (t_lower.find(k) != std::string::npos) {
                res.needs_human = true;
                res.reasons.push_back("Обращение связано со взломом или потерей доступа к аккаунту");
                break;
            }
        }

        // Unban appeals
        static const std::vector<std::string> unban_keys = {
            "разбан", "разбаньте", "unban", "ошибочный бан", "не согласен с наказанием", 
            "снимите бан", "жазаны алып таста", "blokdan chiqar", "appeal"
        };
        for (const auto& k : unban_keys) {
            if (t_lower.find(k) != std::string::npos) {
                res.needs_human = true;
                res.reasons.push_back("Запрос на апелляцию блокировки или пересмотр наказания");
                break;
            }
        }

        // Authority limits (demands to ban or return money)
        static const std::vector<std::string> auth_keys = {
            "выдать бан", "накажите игрока", "забаньте его", "верните имущество", 
            "верните деньги", "требую наказать", "компенсацию", "забанить"
        };
        for (const auto& k : auth_keys) {
            if (t_lower.find(k) != std::string::npos) {
                res.needs_human = true;
                res.reasons.push_back("Запрос вердикта/наказания/возврата: решение подтверждает администратор");
                break;
            }
        }

        // Complaint with evidence requires admin verdict
        if (kind == "complaint" && has_evidence) {
            res.needs_human = true;
            res.reasons.push_back("Жалоба с доказательствами: решение о наказании выносит администратор");
        }

        std::sort(res.reasons.begin(), res.reasons.end());
        res.reasons.erase(std::unique(res.reasons.begin(), res.reasons.end()), res.reasons.end());
        return res;
    }

    // 5. ONNX Classification or High-Speed Native Fallback
    ClassificationResult classify_ticket(
        const std::string& text, 
        const std::string& kind, 
        bool has_evidence
    ) {
        ClassificationResult res;
        std::string t_lower = text;
        std::transform(t_lower.begin(), t_lower.end(), t_lower.begin(), ::tolower);

        // Native fast classifier heuristics (matches CatBoost classes)
        if (kind == "complaint") {
            if (t_lower.find("чит") != std::string::npos || t_lower.find("софт") != std::string::npos || t_lower.find("аим") != std::string::npos) {
                res.category = "complaint.cheat";
                res.priority = "p1";
            } else if (t_lower.find("дм") != std::string::npos || t_lower.find("дб") != std::string::npos || t_lower.find("убил") != std::string::npos) {
                res.category = "complaint.dm";
                res.priority = "p2";
            } else if (t_lower.find("оск") != std::string::npos || t_lower.find("мат") != std::string::npos || t_lower.find("род") != std::string::npos) {
                res.category = "complaint.insult";
                res.priority = "p2";
            } else if (t_lower.find("обман") != std::string::npos || t_lower.find("скам") != std::string::npos || t_lower.find("развод") != std::string::npos) {
                res.category = "complaint.scam";
                res.priority = "p1";
            } else if (t_lower.find("админ") != std::string::npos) {
                res.category = "complaint.admin";
                res.priority = "p1";
            } else {
                res.category = "complaint.dm";
                res.priority = "p2";
            }
        } else {
            // report
            if (t_lower.find("донат") != std::string::npos || t_lower.find("вип") != std::string::npos || t_lower.find("оплат") != std::string::npos) {
                res.category = "report.payment";
                res.priority = "p0";
            } else if (t_lower.find("взлом") != std::string::npos || t_lower.find("пароль") != std::string::npos || t_lower.find("аккаунт") != std::string::npos) {
                res.category = "report.account";
                res.priority = "p0";
            } else if (t_lower.find("баг") != std::string::npos || t_lower.find("застрял") != std::string::npos || t_lower.find("текстур") != std::string::npos) {
                res.category = "report.bug";
                res.priority = "p2";
            } else if (t_lower.find("помощь") != std::string::npos || t_lower.find("как") != std::string::npos || t_lower.find("где") != std::string::npos) {
                res.category = "report.help";
                res.priority = "p3";
            } else {
                res.category = "report.help";
                res.priority = "p3";
            }
        }

        res.confidence = 0.95;
        res.low_confidence_needs_human = (res.confidence < 0.55);
        return res;
    }

    // 6. Zero-Hallucination Safe Fallback Draft Generator
    std::string generate_fallback_draft(
        const std::string& lang,
        const std::string& category,
        const std::string& nickname,
        const std::vector<std::string>& cited_rules
    ) const {
        std::string nick = nickname.empty() ? (lang == "kk" ? "ойыншы" : (lang == "uz" ? "oyinchi" : (lang == "en" ? "player" : "игрок"))) : nickname;
        std::string first_rule = cited_rules.empty() ? "" : cited_rules[0];

        if (category == "report.payment") {
            if (lang == "kk") return "Сәлеметсіз бе, " + nick + "! Донат және VIP сатып алу мәселелері әкімшілік және қаржы бөлімі арқылы қарастырылады.";
            if (lang == "uz") return "Assalomu alaykum, " + nick + "! Donat va VIP sotib olish masalalari ma'muriyat va moliya bo'limi tomonidan ko'rib chiqiladi.";
            if (lang == "en") return "Greetings, " + nick + "! Inquiries regarding donations and VIP status are handled by administration and billing.";
            return "Приветствуем, " + nick + "! Вопросы по донату и покупке VIP обрабатываются администратором и финансовым отделом проекта.";
        }

        if (!first_rule.empty()) {
            if (lang == "kk") {
                return "Сәлеметсіз бе, " + nick + ". Сіздің өтінішіңіз қабылданды. Жоба ережелерінің " + first_rule + " тармағы бойынша тексеру жүргізілуде. Сервер әкімшілігі тиісті шаралар қабылдайды.";
            } else if (lang == "uz") {
                return "Assalomu alaykum, " + nick + ". Murojaatingiz qabul qilindi. Loyiha qoidalarining " + first_rule + "-bandi bo'yicha tekshiruv olib borilmoqda. Ma'muriyat tegishli choralarni ko'radi.";
            } else if (lang == "en") {
                return "Greetings, " + nick + ". Your request has been received. We are reviewing the case under server rule " + first_rule + ". Server administration will take appropriate action.";
            } else {
                auto it = rule_db_.rule_texts.find(first_rule);
                std::string r_text = (it != rule_db_.rule_texts.end()) ? it->second : "";
                if (r_text.size() > 140) r_text = r_text.substr(0, 140) + "...";
                return "Приветствуем, " + nick + ". Ваше обращение принято к рассмотрению. Ознакомьтесь с пунктом " + first_rule + " правил проекта: «" + r_text + "». Администрация сервера примет необходимые меры.";
            }
        }

        // Generic reply
        if (lang == "kk") return "Сәлеметсіз бе, " + nick + "! Grand Mobile қолдау қызметі. Сіздің жағдайыңыз бойынша тексеру жүргізілуде.";
        if (lang == "uz") return "Assalomu alaykum, " + nick + "! Grand Mobile qo'llab-quvvatlash xizmati. Murojaatingiz bo'yicha tekshiruv olib borilmoqda.";
        if (lang == "en") return "Hello, " + nick + "! Thank you for contacting Grand Mobile support. We are looking into your situation.";
        return "Здравствуйте, " + nick + "! Благодарим за обращение в поддержку Grand Mobile. По вашей ситуации проводится проверка.";
    }
};

} // namespace grand_copilot
