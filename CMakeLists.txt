cmake_minimum_required(VERSION 3.16)
project(grand_mobile_server VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Maximum HFT Optimization Flags: -O3 -march=native -flto -DNDEBUG
if(MSVC)
    add_compile_options(/O2 /arch:AVX2 /GL /DNDEBUG /W3)
    add_link_options(/LTCG)
else()
    add_compile_options(-O3 -march=native -flto -DNDEBUG -Wall -Wextra -pthread)
    add_link_options(-flto)
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

# 3. Libcurl
find_package(CURL)

# 4. ONNX Runtime (Optional/System)
find_path(ONNXRUNTIME_INCLUDE_DIR onnxruntime_cxx_api.h)
find_library(ONNXRUNTIME_LIB onnxruntime)

# Target 1: Production Server (grand_mobile_server)
add_executable(grand_mobile_server src/main.cpp)
target_include_directories(grand_mobile_server PRIVATE src ${rapidjson_SOURCE_DIR}/include)
target_link_libraries(grand_mobile_server PRIVATE Crow::Crow Threads::Threads)

# Target 2: Native Benchmark & Predict Tool (benchmark_tool)
add_executable(benchmark_tool src/run_tests.cpp)
target_include_directories(benchmark_tool PRIVATE src ${rapidjson_SOURCE_DIR}/include)
target_link_libraries(benchmark_tool PRIVATE Threads::Threads)

if(CURL_FOUND)
    target_link_libraries(grand_mobile_server PRIVATE CURL::libcurl)
    target_compile_definitions(grand_mobile_server PRIVATE HAS_LIBCURL=1)
    target_link_libraries(benchmark_tool PRIVATE CURL::libcurl)
    target_compile_definitions(benchmark_tool PRIVATE HAS_LIBCURL=1)
endif()

if(ONNXRUNTIME_INCLUDE_DIR AND ONNXRUNTIME_LIB)
    target_include_directories(grand_mobile_server PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
    target_link_libraries(grand_mobile_server PRIVATE ${ONNXRUNTIME_LIB})
    target_compile_definitions(grand_mobile_server PRIVATE HAS_ONNX_RUNTIME=1)

    target_include_directories(benchmark_tool PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
    target_link_libraries(benchmark_tool PRIVATE ${ONNXRUNTIME_LIB})
    target_compile_definitions(benchmark_tool PRIVATE HAS_ONNX_RUNTIME=1)
endif()
