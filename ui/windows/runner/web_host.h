#ifndef RUNNER_WEB_HOST_H_
#define RUNNER_WEB_HOST_H_

#include <flutter/binary_messenger.h>
#include <flutter/encodable_value.h>
#include <flutter/method_channel.h>
#include <windows.h>
#include <wrl.h>

#include <map>
#include <memory>
#include <string>

#include "WebView2.h"

// Host WebView2 langsung di proses Flutter (docs/architecture/v4-native-plan.md N1).
//
// - satu CoreWebView2Environment per folder data akun (jar sama dgn 3.5.x)
// - tiap webview = jendela anak "wadah" milik jendela utama, di atas
//   FlutterView; posisi dari Dart (setRect, piksel fisik)
// - CDP lewat CallDevToolsProtocolMethod + event receiver (tanpa port debug)
// - popup (window.open / target=_blank) TIDAK pernah jadi jendela: halaman
//   utama yang navigasi (OAuth Google tetap di dalam app)
//
// Semua callback WebView2 datang di thread UI ini juga (STA) = thread
// platform Flutter, jadi aman memanggil MethodChannel langsung.
// Channel: "typingbot/web_host". Event ke Dart: invokeMethod("event", map).
class WebHost {
 public:
  WebHost(flutter::BinaryMessenger* messenger, HWND top_level);
  ~WebHost();

  // Tutup semua webview sebelum jendela utama hancur.
  void Shutdown();

  // Fokus balik ke halaman saat jendela aktif lagi (alt-tab saat isi
  // sandi tidak kehilangan fokus).
  void OnActivate(bool active);

  // Jendela utama dipindah: popup bawaan webview (dropdown, autofill)
  // harus ikut posisi baru.
  void OnMove();

 private:
  using Result = std::shared_ptr<flutter::MethodResult<flutter::EncodableValue>>;

  struct View {
    int64_t id = 0;
    HWND container = nullptr;
    bool visible = false;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment> env;
    Microsoft::WRL::ComPtr<ICoreWebView2Controller> controller;
    Microsoft::WRL::ComPtr<ICoreWebView2> webview;
    std::map<std::string, EventRegistrationToken> cdp_subs;
  };

  void Handle(const flutter::MethodCall<flutter::EncodableValue>& call,
              Result result);

  void Create(int64_t id, const std::wstring& folder, const std::wstring& url,
              const flutter::EncodableList& scripts, bool visible,
              Result result);
  void OnControllerReady(int64_t id, ICoreWebView2Controller* controller,
                         const std::wstring& url,
                         const flutter::EncodableList& scripts, Result result);
  void Dispose(int64_t id);
  void SetRect(int x, int y, int w, int h);
  void SetVisible(View* v, bool on);
  void ApplyBounds(View* v);
  View* Find(int64_t id);
  void Emit(int64_t id, const char* type, flutter::EncodableMap fields);

  HWND top_level_;
  RECT rect_{0, 0, 0, 0};
  bool had_focus_ = false;
  std::map<int64_t, std::unique_ptr<View>> views_;
  // false setelah host dibongkar: callback async yang telat jangan
  // menyentuh objek yang sudah mati
  std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
};

#endif  // RUNNER_WEB_HOST_H_
