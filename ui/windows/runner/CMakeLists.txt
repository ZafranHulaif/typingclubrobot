cmake_minimum_required(VERSION 3.14)
project(runner LANGUAGES CXX)

# Define the application target. To change its name, change BINARY_NAME in the
# top-level CMakeLists.txt, not the value here, or `flutter run` will no longer
# work.
#
# Any new source files that you add to the application should be added here.
add_executable(${BINARY_NAME} WIN32
  "flutter_window.cpp"
  "main.cpp"
  "utils.cpp"
  "web_host.cpp"
  "win32_window.cpp"
  "${FLUTTER_MANAGED_DIR}/generated_plugin_registrant.cc"
  "Runner.rc"
  "runner.exe.manifest"
)

# Apply the standard set of build settings. This can be removed for applications
# that need different build settings.
apply_standard_settings(${BINARY_NAME})

# Add preprocessor definitions for the build version.
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION=\"${FLUTTER_VERSION}\"")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_MAJOR=${FLUTTER_VERSION_MAJOR}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_MINOR=${FLUTTER_VERSION_MINOR}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_PATCH=${FLUTTER_VERSION_PATCH}")
target_compile_definitions(${BINARY_NAME} PRIVATE "FLUTTER_VERSION_BUILD=${FLUTTER_VERSION_BUILD}")

# Disable Windows macros that collide with C++ standard library functions.
target_compile_definitions(${BINARY_NAME} PRIVATE "NOMINMAX")

# Add dependency libraries and include directories. Add any application-specific
# dependencies here.
target_link_libraries(${BINARY_NAME} PRIVATE flutter flutter_wrapper_app)
target_link_libraries(${BINARY_NAME} PRIVATE "dwmapi.lib")

# WebView2 SDK (header + loader statis) dari NuGet, diunduh sekali ke folder
# build. Loader statis = tidak ada WebView2Loader.dll yang harus ikut dikirim.
set(WEBVIEW2_VERSION "1.0.2903.40")
set(WEBVIEW2_DIR "${CMAKE_BINARY_DIR}/webview2-${WEBVIEW2_VERSION}")
if(NOT EXISTS "${WEBVIEW2_DIR}/build/native/include/WebView2.h")
  set(WEBVIEW2_PKG "${CMAKE_BINARY_DIR}/webview2-${WEBVIEW2_VERSION}.zip")
  file(DOWNLOAD
    "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/${WEBVIEW2_VERSION}"
    "${WEBVIEW2_PKG}" STATUS WEBVIEW2_DL TLS_VERIFY ON)
  list(GET WEBVIEW2_DL 0 WEBVIEW2_DL_CODE)
  if(NOT WEBVIEW2_DL_CODE EQUAL 0)
    message(FATAL_ERROR "Gagal unduh WebView2 SDK: ${WEBVIEW2_DL}")
  endif()
  file(ARCHIVE_EXTRACT INPUT "${WEBVIEW2_PKG}" DESTINATION "${WEBVIEW2_DIR}")
endif()
target_include_directories(${BINARY_NAME} PRIVATE
  "${WEBVIEW2_DIR}/build/native/include")
target_link_libraries(${BINARY_NAME} PRIVATE
  "${WEBVIEW2_DIR}/build/native/x64/WebView2LoaderStatic.lib"
  "version.lib")
target_include_directories(${BINARY_NAME} PRIVATE "${CMAKE_SOURCE_DIR}")

# Run the Flutter tool portions of the build. This must not be removed.
add_dependencies(${BINARY_NAME} flutter_assemble)
