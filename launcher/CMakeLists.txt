# Pembawa TypingBot.exe (N6). Runtime statis: jalan tanpa VC++ redist.
cmake_minimum_required(VERSION 3.15)
cmake_policy(SET CMP0091 NEW)
project(TypingBotSetup LANGUAGES CXX RC)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")
add_executable(TypingBotSetup WIN32 launcher.cpp launcher.rc)
target_compile_definitions(TypingBotSetup PRIVATE UNICODE _UNICODE)
target_compile_options(TypingBotSetup PRIVATE /W3 /O2 /EHsc)
target_link_libraries(TypingBotSetup PRIVATE shell32 ole32 uuid user32 gdi32)
