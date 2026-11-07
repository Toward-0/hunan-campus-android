cmake_minimum_required(VERSION 3.16)
project(hunan_core C)
set(CMAKE_C_STANDARD 11)
set(BASE ${CMAKE_CURRENT_LIST_DIR}/../../../../vendor/hunan)
file(GLOB MOBILE_ALGOS ${BASE}/src/cipher/algo/android/*.c)
add_library(hunan_core SHARED bridge.c memory_hex.c mobile_bridge.c cipher_support.c ${MOBILE_ALGOS}
    ${BASE}/src/cipher/algo/ios/ios_zsm.c
    ${BASE}/third_party/7z/LzmaDec.c
    ${BASE}/src/utils/sim/SimEvpDes3.c
    ${BASE}/src/hunan/HunanXml.c
    ${BASE}/src/cipher/algo/hunan/aes_double_cbc_hunan.c
    ${BASE}/src/cipher/KeyData.c
    ${BASE}/src/utils/sim/SimEvpAes.c)
target_include_directories(hunan_core PRIVATE ${CMAKE_CURRENT_LIST_DIR}/compat ${BASE}/include ${BASE}/src ${BASE}/third_party)
target_compile_options(hunan_core PRIVATE -Wall -Wextra -Werror=implicit-function-declaration)
if(HUNAN_ISOLATION)
    target_sources(hunan_core PRIVATE compat_probe.c)
    target_compile_definitions(hunan_core PRIVATE HUNAN_ISOLATION=1)
endif()

