#ifndef RUNNER_WEB_HOST_H_
#define RUNNER_WEB_HOST_H_

#include <flutter/binary_messenger.h>
#include <flutter/encodable_value.h>
#include <flutter/method_channel.h>
#include <windows.h>

#include <memory>

// Mengadopsi jendela "wadah" WebView2 milik proses sidecar Python
// (docs/architecture/M0-decision.md §3) ke dalam jendela Flutter.
//
// Aturan: tidak pernah memanggil sinkron ke jendela proses lain selain
// SetParent sekali saat attach. Posisi pakai SWP_ASYNCWINDOWPOS supaya
// sidecar yang macet tidak bisa membekukan UI.
class WebHost {
 public:
  WebHost(flutter::BinaryMessenger* messenger, HWND top_level);
  ~WebHost();

  // Lepas wadah sebelum jendela Flutter hancur (kalau tidak, kontrol
  // WebView2 milik sidecar ikut hancur di tengah jalan).
  void Detach();

  // Fokus balik ke halaman saat jendela aktif lagi (alt-tab saat isi
  // sandi tidak kehilangan fokus).
  void OnActivate(bool active);

 private:
  void Attach(HWND child);
  void SetRect(int x, int y, int w, int h);

  HWND top_level_;
  HWND child_ = nullptr;
  bool child_had_focus_ = false;
  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
};

#endif  // RUNNER_WEB_HOST_H_
