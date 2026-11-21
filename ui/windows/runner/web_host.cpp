#include "web_host.h"

#include <flutter/standard_method_codec.h>

namespace {

// Ambil angka dari map argumen Dart (int kecil = int32, besar = int64,
// pecahan = double).
int64_t ArgInt(const flutter::EncodableMap& m, const char* key) {
  auto it = m.find(flutter::EncodableValue(key));
  if (it == m.end()) return 0;
  const auto& v = it->second;
  if (auto p = std::get_if<int32_t>(&v)) return *p;
  if (auto p = std::get_if<int64_t>(&v)) return *p;
  if (auto p = std::get_if<double>(&v)) return static_cast<int64_t>(*p);
  return 0;
}

}  // namespace

WebHost::WebHost(flutter::BinaryMessenger* messenger, HWND top_level)
    : top_level_(top_level) {
  // anak harus digambar di atas FlutterView & tidak ditimpa
  LONG style = GetWindowLong(top_level_, GWL_STYLE);
  SetWindowLong(top_level_, GWL_STYLE, style | WS_CLIPCHILDREN);

  channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      messenger, "typingbot/web_host",
      &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler(
      [this](const flutter::MethodCall<flutter::EncodableValue>& call,
             std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>>
                 result) {
        const auto* args =
            std::get_if<flutter::EncodableMap>(call.arguments());
        if (!args) {
          result->Error("bad_args", "map expected");
          return;
        }
        if (call.method_name() == "attach") {
          Attach(reinterpret_cast<HWND>(ArgInt(*args, "hwnd")));
          result->Success();
        } else if (call.method_name() == "setRect") {
          SetRect(static_cast<int>(ArgInt(*args, "x")),
                  static_cast<int>(ArgInt(*args, "y")),
                  static_cast<int>(ArgInt(*args, "w")),
                  static_cast<int>(ArgInt(*args, "h")));
          result->Success();
        } else {
          result->NotImplemented();
        }
      });
}

WebHost::~WebHost() { Detach(); }

void WebHost::Attach(HWND child) {
  if (child == child_) return;
  Detach();
  if (!child || !IsWindow(child)) return;
  // WS_POPUP (Toplevel Tk tanpa bingkai) -> WS_CHILD milik jendela kita
  LONG style = GetWindowLong(child, GWL_STYLE);
  style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME);
  style |= WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS;
  SetWindowLong(child, GWL_STYLE, style);
  SetParent(child, top_level_);
  child_ = child;
  // di atas FlutterView (saudara), ukuran menyusul dari setRect
  SetWindowPos(child_, HWND_TOP, 0, 0, 0, 0,
               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS |
                   SWP_FRAMECHANGED);
}

void WebHost::SetRect(int x, int y, int w, int h) {
  if (!child_) return;
  if (!IsWindow(child_)) {
    child_ = nullptr;
    return;
  }
  // tanpa SWP_SHOWWINDOW: tampil/sembunyi milik sidecar (cover & popup)
  SetWindowPos(child_, HWND_TOP, x, y, w < 1 ? 1 : w, h < 1 ? 1 : h,
               SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
}

void WebHost::Detach() {
  if (!child_) return;
  if (IsWindow(child_)) {
    ShowWindowAsync(child_, SW_HIDE);
    SetParent(child_, nullptr);
    LONG style = GetWindowLong(child_, GWL_STYLE);
    SetWindowLong(child_, GWL_STYLE, (style & ~WS_CHILD) | WS_POPUP);
  }
  child_ = nullptr;
}

void WebHost::OnActivate(bool active) {
  if (!child_) return;
  if (!active) {
    HWND f = GetFocus();
    child_had_focus_ = f && (f == child_ || IsChild(child_, f));
  } else if (child_had_focus_) {
    SetFocus(child_);
  }
}
