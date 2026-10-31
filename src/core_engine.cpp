#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <string>
#include <vector>
#include <regex>
#include <algorithm>
#include <cctype>
#include <sstream>

namespace py = pybind11;

// 1. Fast CP1251 -> Kazakh Cyrillic UTF-8 Replacement Table
static const std::vector<std::pair<std::string, std::string>> KZ_REPLACEMENTS = {
    {"ќ", "қ"}, {"Ќ", "Қ"},
    {"ґ", "ғ"}, {"Ґ", "Ғ"},
    {"ѕ", "ң"}, {"Ѕ", "Ң"},
    {"є", "ә"}, {"Є", "Ә"},
    {"ј", "ө"}, {"Ј", "Ө"},
    {"ў", "ұ"}, {"Ў", "Ұ"},
    {"ї", "ү"}, {"Ї", "Ү"}
};

// Replace all occurrences of from with to in str
static void replace_all(std::string& str, const std::string& from, const std::string& to) {
    if (from.empty()) return;
    size_t start_pos = 0;
    while ((start_pos = str.find(from, start_pos)) != std::string::npos) {
        str.replace(start_pos, from.length(), to);
        start_pos += to.length();
    }
}

// Normalize cp1251 Kazakh and collapse whitespaces in C++
std::string fix_cp1251_kz(const std::string& input) {
    if (input.empty()) return "";
    std::string result = input;
    
    // Replace cp1251 Kazakh characters
    for (const auto& pair : KZ_REPLACEMENTS) {
        replace_all(result, pair.first, pair.second);
    }
    
    // Normalize newlines, tabs, and carriage returns to space
    for (char& c : result) {
        if (c == '\r' || c == '\n' || c == '\t') {
            c = ' ';
        }
    }
    
    // Collapse consecutive whitespaces and trim
    std::string collapsed;
    collapsed.reserve(result.size());
    bool in_space = false;
    for (char c : result) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            if (!in_space) {
                collapsed.push_back(' ');
                in_space = true;
            }
        } else {
            collapsed.push_back(c);
            in_space = false;
        }
    }
    
    // Trim leading/trailing spaces
    size_t start = collapsed.find_first_not_of(' ');
    if (start == std::string::npos) return "";
    size_t end = collapsed.find_last_not_of(' ');
    return collapsed.substr(start, end - start + 1);
}

// 2. High-Performance Levenshtein Distance in C++
int levenshtein_distance(const std::string& s1, const std::string& s2) {
    const size_t m = s1.size();
    const size_t n = s2.size();
    if (m == 0) return static_cast<int>(n);
    if (n == 0) return static_cast<int>(m);

    std::vector<int> prev(n + 1);
    std::vector<int> curr(n + 1);

    for (size_t j = 0; j <= n; ++j) {
        prev[j] = static_cast<int>(j);
    }

    for (size_t i = 1; i <= m; ++i) {
        curr[0] = static_cast<int>(i);
        for (size_t j = 1; j <= n; ++j) {
            int cost = (s1[i - 1] == s2[j - 1]) ? 0 : 1;
            curr[j] = std::min({
                prev[j] + 1,        // deletion
                curr[j - 1] + 1,    // insertion
                prev[j - 1] + cost  // substitution
            });
        }
        prev = curr;
    }

    return curr[n];
}

double fuzzy_similarity(const std::string& s1, const std::string& s2) {
    if (s1.empty() && s2.empty()) return 1.0;
    if (s1.empty() || s2.empty()) return 0.0;
    int dist = levenshtein_distance(s1, s2);
    size_t max_len = std::max(s1.size(), s2.size());
    return 1.0 - (static_cast<double>(dist) / static_cast<double>(max_len));
}

// 3. Fast C++ Fact & Entity Extractor
py::dict extract_facts_cpp(
    const std::string& text,
    const std::string& raw_refs,
    int images_count,
    const std::string& reported_nick,
    const std::string& server_str
) {
    py::dict result;
    std::string norm_text = fix_cp1251_kz(text);
    std::string norm_raw = fix_cp1251_kz(raw_refs);

    // 1. Nickname
    std::string nick = reported_nick;
    if (nick.empty() || nick == "None") {
        static const std::regex nick_regex(R"([A-Za-zА-Яа-яЁё0-9]+_[A-Za-zА-Яа-яЁё0-9]+)");
        std::smatch match;
        if (std::regex_search(norm_text, match, nick_regex)) {
            nick = match.str(0);
        } else if (norm_text.find("<nick>") != std::string::npos) {
            nick = "<nick>";
        } else {
            nick = "";
        }
    }

    // 2. Rule references (e.g., 5.3, 1.1)
    std::vector<std::string> refs;
    static const std::regex rule_regex(R"(\b\d+\.\d+(?:\.\d+)?\b)");
    
    auto search_refs = [&](const std::string& s) {
        auto begin = std::sregex_iterator(s.begin(), s.end(), rule_regex);
        auto end = std::sregex_iterator();
        for (std::sregex_iterator i = begin; i != end; ++i) {
            std::string r = (*i).str();
            if (std::find(refs.begin(), refs.end(), r) == refs.end()) {
                refs.push_back(r);
            }
        }
    };
    search_refs(norm_raw);
    search_refs(norm_text);

    // Green zone check
    static const std::regex gz_regex(R"(\b(?:gz|гз|зз)\b)", std::regex_constants::icase);
    std::string combined = norm_raw + " " + norm_text;
    if (std::regex_search(combined, gz_regex)) {
        if (std::find(refs.begin(), refs.end(), "GZ") == refs.end()) {
            refs.push_back("GZ");
        }
    }
    std::sort(refs.begin(), refs.end());

    // 3. Evidence check
    bool has_evidence = (images_count > 0);
    if (!has_evidence) {
        static const std::regex ev_regex(
            R"(скрин|видео|фрапс|пруф|доказ|доки|запись|<url>|дәлел|далел|skrin|video|proof|dalil|dalillar|screen|screenshot|зафиксировал|заснял|снял)",
            std::regex_constants::icase
        );
        if (std::regex_search(norm_text, ev_regex)) {
            has_evidence = true;
        }
    }

    // 4. Server check
    std::string server = server_str;
    if (server.empty()) {
        static const std::regex srv_regex(R"((?:сервер[а-я]*|server)\s*[:#№]?\s*(\d+|[a-zA-Z]+))", std::regex_constants::icase);
        std::smatch sm;
        if (std::regex_search(norm_text, sm, srv_regex)) {
            server = sm.str(1);
        }
    }

    if (nick.empty()) {
        result["nickname"] = py::none();
    } else {
        result["nickname"] = nick;
    }
    result["rule_refs"] = refs;
    result["has_evidence"] = has_evidence;
    if (server.empty()) {
        result["server"] = py::none();
    } else {
        result["server"] = server;
    }

    return result;
}

// 4. C++ Fuzzy Rule Searcher using Levenshtein distance
py::list fuzzy_match_rule(
    const std::string& query,
    const std::vector<std::string>& rule_texts,
    const std::vector<std::string>& rule_refs,
    double threshold = 0.5
) {
    py::list matched_refs;
    if (rule_texts.size() != rule_refs.size()) return matched_refs;

    std::string q_clean = fix_cp1251_kz(query);
    std::transform(q_clean.begin(), q_clean.end(), q_clean.begin(), ::tolower);

    // Tokenize query words
    std::vector<std::string> q_words;
    std::istringstream iss(q_clean);
    std::string word;
    while (iss >> word) {
        if (word.size() >= 3) {
            q_words.push_back(word);
        }
    }

    for (size_t i = 0; i < rule_texts.size(); ++i) {
        std::string r_text = rule_texts[i];
        std::transform(r_text.begin(), r_text.end(), r_text.begin(), ::tolower);
        
        bool found = false;
        // Direct substring check
        for (const auto& qw : q_words) {
            if (r_text.find(qw) != std::string::npos) {
                found = true;
                break;
            }
        }
        
        // Levenshtein fuzzy match if not directly matched
        if (!found) {
            for (const auto& qw : q_words) {
                std::istringstream r_iss(r_text);
                std::string rw;
                while (r_iss >> rw) {
                    if (std::abs(static_cast<int>(rw.size()) - static_cast<int>(qw.size())) <= 2) {
                        double sim = fuzzy_similarity(qw, rw);
                        if (sim >= threshold) {
                            found = true;
                            break;
                        }
                    }
                }
                if (found) break;
            }
        }

        if (found) {
            matched_refs.append(rule_refs[i]);
        }
    }

    return matched_refs;
}

PYBIND11_MODULE(core_engine, m) {
    m.doc() = "Grand Mobile Support Copilot — High-Performance C++ Core Module (C++17)";
    m.def("fix_cp1251_kz", &fix_cp1251_kz, "Fast C++ replacement of CP1251 distorted Kazakh characters and whitespace normalization");
    m.def("levenshtein_distance", &levenshtein_distance, "Fast Levenshtein distance calculation in C++");
    m.def("fuzzy_similarity", &fuzzy_similarity, "Calculates similarity ratio (0.0 to 1.0) using C++ Levenshtein distance");
    m.def("extract_facts_cpp", &extract_facts_cpp, "Fast C++ fact, nickname, server, evidence and rule extractor");
    m.def("fuzzy_match_rule", &fuzzy_match_rule, "C++ Fuzzy rule search across rules database with threshold");
}

