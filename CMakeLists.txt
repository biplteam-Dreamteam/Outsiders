cmake_minimum_required(VERSION 3.16)
project(grand_mobile_server VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Optimization flags for HFT-level speed
if(MSVC)
    add_compile_options(/O2 /arch:AVX2 /W3)
else()
    add_compile_options(-O3 -march=native -Wall -Wextra -pthread)
endif()

# Threading
find_package(Threads REQUIRED)

# Include FetchContent for dependencies
include(FetchContent)

# 1. RapidJSON
FetchContent_Declare(
    rapidjson
    GIT_REPOSITORY https://github.com/Tencent/rapidjson.git
    GIT_TAG        v1.1.0
)
FetchContent_MakeAvailable(rapidjson)

# 2. Crow C++ Async Framework
FetchContent_Declare(
    crow
    GIT_REPOSITORY https://github.com/CrowCpp/Crow.git
    GIT_TAG        v1.0+5
)
set(CROW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CROW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(crow)

# 3. Libcurl (for native HTTP calls to LLM engine)
find_package(CURL)

# 4. ONNX Runtime (Optional/System)
find_path(ONNXRUNTIME_INCLUDE_DIR onnxruntime_cxx_api.h)
find_library(ONNXRUNTIME_LIB onnxruntime)

# Source files
set(SOURCES
    src/main.cpp
    src/ticket_processor.hpp
    src/dynamic_batcher.hpp
)

add_executable(grand_mobile_server ${SOURCES})

target_include_directories(grand_mobile_server PRIVATE
    src
    ${rapidjson_SOURCE_DIR}/include
)

target_link_libraries(grand_mobile_server PRIVATE
    Crow::Crow
    Threads::Threads
)

if(CURL_FOUND)
    target_link_libraries(grand_mobile_server PRIVATE CURL::libcurl)
    target_compile_definitions(grand_mobile_server PRIVATE HAS_LIBCURL=1)
endif()

if(ONNXRUNTIME_INCLUDE_DIR AND ONNXRUNTIME_LIB)
    target_include_directories(grand_mobile_server PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
    target_link_libraries(grand_mobile_server PRIVATE ${ONNXRUNTIME_LIB})
    target_compile_definitions(grand_mobile_server PRIVATE HAS_ONNX_RUNTIME=1)
    message(STATUS "ONNX Runtime found and linked!")
else()
    message(STATUS "ONNX Runtime not found in system paths, native C++ high-speed classifier enabled.")
endif()
