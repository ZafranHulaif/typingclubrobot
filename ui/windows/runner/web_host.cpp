#include "web_host.h"

#include <flutter/standard_method_codec.h>

#include <psapi.h>

#include <cstdio>
#include <vector>

using flutter::EncodableList;
using flutter::EncodableMap;
using flutter::EncodableValue;
using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

namespace {

const wchar_t kContainerClass[] = L"TypingBotWebContainer";

// ---------------------------------------------------------- utf8 <-> utf16
std::wstring Wide(const std::string& s) {
  if (s.empty()) return std::wstring();
  int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()),
                              nullptr, 0);
  std::wstring out(static_cast<size_t>(n), L'\0');
  MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()),
                      out.data(), n);
  return out;
}

std::string Utf8(const wchar_t* s) {
  if (!s || !*s) return std::string();
  int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0, nullptr, nullptr);
  if (n <= 1) return std::string();
  std::string out(static_cast<size_t>(n - 1), '\0');
  WideCharToMultiByte(CP_UTF8, 0, s, -1, out.data(), n, nullptr, nullptr);
  return out;
}

// string milik WebView2 (CoTaskMem) -> utf8, lalu dibebaskan
std::string TakeUtf8(LPWSTR s) {
  std::string out = Utf8(s);
  if (s) CoTaskMemFree(s);
  return out;
}

std::string HrText(HRESULT hr) {
  char buf[32];
  snprintf(buf, sizeof(buf), "0x%08lX", static_cast<unsigned long>(hr));
  return buf;
}

// ---------------------------------------------------------- argumen Dart
const EncodableValue* Arg(const EncodableMap& m, const char* key) {
  auto it = m.find(EncodableValue(key));
  return it == m.end() ? nullptr : &it->second;
}

int64_t ArgInt(const EncodableMap& m, const char* key) {
  const EncodableValue* v = Arg(m, key);
  if (!v) return 0;
  if (auto p = std::get_if<int32_t>(v)) return *p;
  if (auto p = std::get_if<int64_t>(v)) return *p;
  if (auto p = std::get_if<double>(v)) return static_cast<int64_t>(*p);
  return 0;
}

std::string ArgStr(const EncodableMap& m, const char* key) {
  const EncodableValue* v = Arg(m, key);
  if (!v) return std::string();
  if (auto p = std::get_if<std::string>(v)) return *p;
  return std::string();
}

// daftar datar [x,y,w,h, ...] -> RECT; lubang kosong/rusak dibuang
std::vector<RECT> ArgRects(const EncodableMap& m, const char* key) {
  std::vector<int> n;
  const EncodableValue* v = Arg(m, key);
  if (!v) return {};
  if (auto list = std::get_if<EncodableList>(v)) {
    for (const auto& e : *list) {
      if (auto p = std::get_if<int32_t>(&e)) {
        n.push_back(*p);
      } else if (auto p64 = std::get_if<int64_t>(&e)) {
        n.push_back(static_cast<int>(*p64));
      } else if (auto pd = std::get_if<double>(&e)) {
        n.push_back(static_cast<int>(*pd));
      } else {
        n.push_back(0);
      }
    }
  } else if (auto i32 = std::get_if<std::vector<int32_t>>(v)) {
    // Int32List dari Dart
    n.assign(i32->begin(), i32->end());
  }
  std::vector<RECT> out;
  for (size_t i = 0; i + 3 < n.size(); i += 4) {
    if (n[i + 2] <= 0 || n[i + 3] <= 0) continue;
    out.push_back(RECT{n[i], n[i + 1], n[i] + n[i + 2], n[i + 1] + n[i + 3]});
  }
  return out;
}

bool ArgBool(const EncodableMap& m, const char* key) {
  const EncodableValue* v = Arg(m, key);
  if (!v) return false;
  if (auto p = std::get_if<bool>(v)) return *p;
  return false;
}

void RegisterContainerClass() {
  static bool done = false;
  if (done) return;
  WNDCLASSEXW wc{};
  wc.cbSize = sizeof(wc);
  wc.lpfnWndProc = DefWindowProcW;
  wc.hInstance = GetModuleHandle(nullptr);
  wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
  // tanpa kuas: wadah tak pernah dicat sendiri (tak ada kilat warna)
  wc.hbrBackground = nullptr;
  wc.lpszClassName = kContainerClass;
  RegisterClassExW(&wc);
  done = true;
}

}  // namespace

WebHost::WebHost(flutter::BinaryMessenger* messenger, HWND top_level)
    : top_level_(top_level) {
  // anak (wadah webview) jangan ditimpa saat jendela utama digambar
  LONG style = GetWindowLong(top_level_, GWL_STYLE);
  SetWindowLong(top_level_, GWL_STYLE, style | WS_CLIPCHILDREN);
  RegisterContainerClass();

  channel_ = std::make_unique<flutter::MethodChannel<EncodableValue>>(
      messenger, "typingbot/web_host",
      &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler(
      [this](const flutter::MethodCall<EncodableValue>& call,
             std::unique_ptr<flutter::MethodResult<EncodableValue>> result) {
        Handle(call, Result(std::move(result)));
      });
}

WebHost::~WebHost() { Shutdown(); }

void WebHost::Shutdown() {
  *alive_ = false;
  if (channel_) channel_->SetMethodCallHandler(nullptr);
  std::vector<int64_t> ids;
  for (auto& kv : views_) ids.push_back(kv.first);
  for (int64_t id : ids) Dispose(id);
}

WebHost::View* WebHost::Find(int64_t id) {
  auto it = views_.find(id);
  return it == views_.end() ? nullptr : it->second.get();
}

void WebHost::Emit(int64_t id, const char* type, EncodableMap fields) {
  if (!*alive_ || !channel_) return;
  fields[EncodableValue("id")] = EncodableValue(id);
  fields[EncodableValue("type")] = EncodableValue(type);
  channel_->InvokeMethod("event",
                         std::make_unique<EncodableValue>(std::move(fields)));
}

// ================================================================ dispatch
void WebHost::Handle(const flutter::MethodCall<EncodableValue>& call,
                     Result result) {
  const std::string& m = call.method_name();
  static const EncodableMap kEmpty;
  const auto* argp = std::get_if<EncodableMap>(call.arguments());
  const EncodableMap& a = argp ? *argp : kEmpty;

  if (m == "version") {
    LPWSTR ver = nullptr;
    HRESULT hr = GetAvailableCoreWebView2BrowserVersionString(nullptr, &ver);
    result->Success(EncodableValue(SUCCEEDED(hr) ? TakeUtf8(ver) : ""));
    return;
  }
  if (m == "setRect") {
    SetRect(static_cast<int>(ArgInt(a, "x")), static_cast<int>(ArgInt(a, "y")),
            static_cast<int>(ArgInt(a, "w")), static_cast<int>(ArgInt(a, "h")));
    result->Success();
    return;
  }
  if (m == "blur") {
    // popup Flutter dibuka: fokus keyboard pindah ke FlutterView, supaya
    // klik berikutnya di halaman memicu GotFocus (= tutup popup)
    if (backdrop_) SetFocus(backdrop_);
    result->Success();
    return;
  }
  if (m == "setHoles") {
    SetHoles(ArgRects(a, "rects"), static_cast<int>(ArgInt(a, "radius")));
    result->Success();
    return;
  }
  if (m == "create") {
    const EncodableValue* sv = Arg(a, "scripts");
    const EncodableList* scripts = sv ? std::get_if<EncodableList>(sv) : nullptr;
    Create(ArgInt(a, "id"), Wide(ArgStr(a, "folder")), Wide(ArgStr(a, "url")),
           scripts ? *scripts : EncodableList(), ArgBool(a, "visible"), result);
    return;
  }

  const int64_t id = ArgInt(a, "id");
  if (m == "dispose") {
    Dispose(id);
    result->Success();
    return;
  }
  View* v = Find(id);
  if (!v || !v->webview) {
    result->Error("no_view", "webview belum siap / tidak ada");
    return;
  }

  if (m == "setVisible") {
    SetVisible(v, ArgBool(a, "on"));
    result->Success();
  } else if (m == "navigate") {
    HRESULT hr = v->webview->Navigate(Wide(ArgStr(a, "url")).c_str());
    if (FAILED(hr)) {
      result->Error("navigate_failed", HrText(hr));
    } else {
      result->Success();
    }
  } else if (m == "reload") {
    v->webview->Reload();
    result->Success();
  } else if (m == "goBack") {
    v->webview->GoBack();
    result->Success();
  } else if (m == "setMuted") {
    // bisukan semua suara halaman (video, efek ketik, minigame). Butuh
    // runtime 101+ (ICoreWebView2_8); lebih tua = tidak bisa dibisukan.
    ComPtr<ICoreWebView2_8> w8;
    if (SUCCEEDED(v->webview.As(&w8)) && w8) {
      HRESULT hr = w8->put_IsMuted(ArgBool(a, "on") ? TRUE : FALSE);
      if (FAILED(hr)) {
        result->Error("mute_failed", HrText(hr));
      } else {
        result->Success();
      }
    } else {
      result->Error("mute_unsupported", "runtime WebView2 terlalu lama");
    }
  } else if (m == "memInfo") {
    // memori tiap proses WebView2 (browser / renderer / gpu / utility),
    // utk log diagnosa 'app berat'. Runtime 1.0.1108+ (Environment8).
    ComPtr<ICoreWebView2Environment8> e8;
    ComPtr<ICoreWebView2ProcessInfoCollection> list;
    UINT32 n = 0;
    if (!v->env || FAILED(v->env.As(&e8)) || !e8 ||
        FAILED(e8->GetProcessInfos(&list)) || !list ||
        FAILED(list->get_Count(&n))) {
      result->Error("mem_unsupported", "runtime WebView2 terlalu lama");
      return;
    }
    EncodableList out;
    for (UINT32 i = 0; i < n; ++i) {
      ComPtr<ICoreWebView2ProcessInfo> pi;
      if (FAILED(list->GetValueAtIndex(i, &pi)) || !pi) continue;
      INT32 pid = 0;
      COREWEBVIEW2_PROCESS_KIND kind = COREWEBVIEW2_PROCESS_KIND_BROWSER;
      pi->get_ProcessId(&pid);
      pi->get_Kind(&kind);
      const char* k = "lain";
      switch (kind) {
        case COREWEBVIEW2_PROCESS_KIND_BROWSER: k = "browser"; break;
        case COREWEBVIEW2_PROCESS_KIND_RENDERER: k = "renderer"; break;
        case COREWEBVIEW2_PROCESS_KIND_GPU: k = "gpu"; break;
        case COREWEBVIEW2_PROCESS_KIND_UTILITY:
        case COREWEBVIEW2_PROCESS_KIND_SANDBOXED_UTILITY: k = "utility"; break;
        default: break;
      }
      int64_t priv = 0, ws = 0;
      HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                             static_cast<DWORD>(pid));
      if (h) {
        PROCESS_MEMORY_COUNTERS_EX pmc{};
        pmc.cb = sizeof(pmc);
        if (K32GetProcessMemoryInfo(
                h, reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc),
                sizeof(pmc))) {
          priv = static_cast<int64_t>(pmc.PrivateUsage);
          ws = static_cast<int64_t>(pmc.WorkingSetSize);
        }
        CloseHandle(h);
      }
      EncodableMap r;
      r[EncodableValue("kind")] = EncodableValue(k);
      r[EncodableValue("pid")] = EncodableValue(static_cast<int64_t>(pid));
      r[EncodableValue("private")] = EncodableValue(priv);
      r[EncodableValue("ws")] = EncodableValue(ws);
      out.push_back(EncodableValue(r));
    }
    result->Success(EncodableValue(out));
  } else if (m == "focus") {
    v->controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
    result->Success();
  } else if (m == "info") {
    LPWSTR src = nullptr, title = nullptr;
    v->webview->get_Source(&src);
    v->webview->get_DocumentTitle(&title);
    EncodableMap r;
    r[EncodableValue("url")] = EncodableValue(TakeUtf8(src));
    r[EncodableValue("title")] = EncodableValue(TakeUtf8(title));
    result->Success(EncodableValue(r));
  } else if (m == "addScript") {
    HRESULT hr = v->webview->AddScriptToExecuteOnDocumentCreated(
        Wide(ArgStr(a, "js")).c_str(),
        Callback<ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler>(
            [result](HRESULT err, LPCWSTR sid) -> HRESULT {
              if (FAILED(err)) {
                result->Error("script_failed", HrText(err));
              } else {
                result->Success(EncodableValue(Utf8(sid)));
              }
              return S_OK;
            })
            .Get());
    if (FAILED(hr)) result->Error("script_failed", HrText(hr));
  } else if (m == "removeScript") {
    v->webview->RemoveScriptToExecuteOnDocumentCreated(
        Wide(ArgStr(a, "sid")).c_str());
    result->Success();
  } else if (m == "eval") {
    // hasil = JSON (string "null" kalau undefined)
    HRESULT hr = v->webview->ExecuteScript(
        Wide(ArgStr(a, "js")).c_str(),
        Callback<ICoreWebView2ExecuteScriptCompletedHandler>(
            [result](HRESULT err, LPCWSTR json) -> HRESULT {
              if (FAILED(err)) {
                result->Error("eval_failed", HrText(err));
              } else {
                result->Success(EncodableValue(Utf8(json)));
              }
              return S_OK;
            })
            .Get());
    if (FAILED(hr)) result->Error("eval_failed", HrText(hr));
  } else if (m == "cdp") {
    std::string params = ArgStr(a, "params");
    if (params.empty()) params = "{}";
    auto done = Callback<ICoreWebView2CallDevToolsProtocolMethodCompletedHandler>(
        [result](HRESULT err, LPCWSTR json) -> HRESULT {
          if (FAILED(err)) {
            // json berisi objek error CDP {code, message}
            result->Error("cdp_failed", Utf8(json));
          } else {
            result->Success(EncodableValue(Utf8(json)));
          }
          return S_OK;
        });
    // session kosong = halaman utama; terisi = target anak (iframe lintas
    // origin, hasil Target.setAutoAttach flatten) - N2
    const std::string session = ArgStr(a, "session");
    HRESULT hr = E_NOINTERFACE;
    if (session.empty()) {
      hr = v->webview->CallDevToolsProtocolMethod(
          Wide(ArgStr(a, "method")).c_str(), Wide(params).c_str(), done.Get());
    } else {
      ComPtr<ICoreWebView2_11> w11;
      if (SUCCEEDED(v->webview.As(&w11)) && w11) {
        hr = w11->CallDevToolsProtocolMethodForSession(
            Wide(session).c_str(), Wide(ArgStr(a, "method")).c_str(),
            Wide(params).c_str(), done.Get());
      }
    }
    if (FAILED(hr)) result->Error("cdp_failed", HrText(hr));
  } else if (m == "cdpSubscribe") {
    std::string ev = ArgStr(a, "event");
    if (v->cdp_subs.count(ev)) {
      result->Success();
      return;
    }
    ComPtr<ICoreWebView2DevToolsProtocolEventReceiver> rx;
    HRESULT hr = v->webview->GetDevToolsProtocolEventReceiver(
        Wide(ev).c_str(), &rx);
    if (FAILED(hr) || !rx) {
      result->Error("cdp_failed", HrText(hr));
      return;
    }
    EventRegistrationToken tok{};
    std::shared_ptr<bool> alive = alive_;
    rx->add_DevToolsProtocolEventReceived(
        Callback<ICoreWebView2DevToolsProtocolEventReceivedEventHandler>(
            [this, alive, id, ev](
                ICoreWebView2*,
                ICoreWebView2DevToolsProtocolEventReceivedEventArgs* args)
                -> HRESULT {
              if (!*alive) return S_OK;
              LPWSTR json = nullptr;
              args->get_ParameterObjectAsJson(&json);
              EncodableMap f;
              f[EncodableValue("event")] = EncodableValue(ev);
              f[EncodableValue("params")] = EncodableValue(TakeUtf8(json));
              // event dari target anak (iframe lintas origin) bawa sessionId
              ComPtr<ICoreWebView2DevToolsProtocolEventReceivedEventArgs2> a2;
              if (SUCCEEDED(args->QueryInterface(IID_PPV_ARGS(&a2))) && a2) {
                LPWSTR sid = nullptr;
                if (SUCCEEDED(a2->get_SessionId(&sid))) {
                  f[EncodableValue("session")] = EncodableValue(TakeUtf8(sid));
                }
              }
              Emit(id, "cdp", std::move(f));
              return S_OK;
            })
            .Get(),
        &tok);
    v->cdp_subs[ev] = tok;
    result->Success();
  } else if (m == "cdpUnsubscribe") {
    std::string ev = ArgStr(a, "event");
    auto it = v->cdp_subs.find(ev);
    if (it != v->cdp_subs.end()) {
      ComPtr<ICoreWebView2DevToolsProtocolEventReceiver> rx;
      if (SUCCEEDED(v->webview->GetDevToolsProtocolEventReceiver(
              Wide(ev).c_str(), &rx)) &&
          rx) {
        rx->remove_DevToolsProtocolEventReceived(it->second);
      }
      v->cdp_subs.erase(it);
    }
    result->Success();
  } else {
    result->NotImplemented();
  }
}

// ================================================================ buat
void WebHost::Create(int64_t id, const std::wstring& folder,
                     const std::wstring& url, const EncodableList& scripts,
                     bool visible, Result result) {
  if (Find(id)) {
    result->Error("exists", "id webview sudah dipakai");
    return;
  }
  auto view = std::make_unique<View>();
  view->id = id;
  view->visible = visible;
  // wadah: anak jendela utama, di atas FlutterView, mulai tersembunyi
  view->container = CreateWindowExW(
      0, kContainerClass, L"", WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
      rect_.left, rect_.top, rect_.right - rect_.left,
      rect_.bottom - rect_.top, top_level_, nullptr, GetModuleHandle(nullptr),
      nullptr);
  if (!view->container) {
    result->Error("create_failed", "wadah gagal dibuat");
    return;
  }
  views_[id] = std::move(view);

  std::shared_ptr<bool> alive = alive_;
  HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
      nullptr, folder.empty() ? nullptr : folder.c_str(), nullptr,
      Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
          [this, alive, id, url, scripts, result](
              HRESULT err, ICoreWebView2Environment* env) -> HRESULT {
            if (!*alive) return S_OK;
            View* v = Find(id);
            if (!v) {
              result->Error("disposed", "webview dibuang sebelum siap");
              return S_OK;
            }
            if (FAILED(err) || !env) {
              Dispose(id);
              result->Error(
                  err == HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND)
                      ? "no_runtime"
                      : "env_failed",
                  HrText(err));
              return S_OK;
            }
            v->env = env;
            HRESULT hr2 = env->CreateCoreWebView2Controller(
                v->container,
                Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                    [this, alive, id, url, scripts, result](
                        HRESULT err2,
                        ICoreWebView2Controller* ctl) -> HRESULT {
                      if (!*alive) {
                        if (ctl) ctl->Close();
                        return S_OK;
                      }
                      if (FAILED(err2) || !ctl) {
                        Dispose(id);
                        result->Error("controller_failed", HrText(err2));
                        return S_OK;
                      }
                      OnControllerReady(id, ctl, url, scripts, result);
                      return S_OK;
                    })
                    .Get());
            if (FAILED(hr2)) {
              Dispose(id);
              result->Error("controller_failed", HrText(hr2));
            }
            return S_OK;
          })
          .Get());
  if (FAILED(hr)) {
    Dispose(id);
    result->Error(hr == HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND) ? "no_runtime"
                                                                 : "env_failed",
                  HrText(hr));
  }
}

void WebHost::OnControllerReady(int64_t id, ICoreWebView2Controller* ctl,
                                const std::wstring& url,
                                const EncodableList& scripts, Result result) {
  View* v = Find(id);
  if (!v) {
    ctl->Close();
    result->Error("disposed", "webview dibuang sebelum siap");
    return;
  }
  v->controller = ctl;
  ctl->get_CoreWebView2(&v->webview);

  // latar putih (halaman edclub terang) - masa renderer belum siap
  // tidak tampak hitam
  ComPtr<ICoreWebView2Controller2> ctl2;
  if (SUCCEEDED(ctl->QueryInterface(IID_PPV_ARGS(&ctl2))) && ctl2) {
    COREWEBVIEW2_COLOR white{255, 255, 255, 255};
    ctl2->put_DefaultBackgroundColor(white);
  }
  ComPtr<ICoreWebView2Settings> settings;
  if (SUCCEEDED(v->webview->get_Settings(&settings)) && settings) {
    settings->put_IsStatusBarEnabled(FALSE);
    settings->put_IsZoomControlEnabled(FALSE);
  }
  // halaman selalu tema terang (edclub + login Google), tidak ikut tema
  // gelap Windows. Butuh runtime 105+; kalau belum ada ya dilewati.
  ComPtr<ICoreWebView2_13> w13;
  if (SUCCEEDED(v->webview.As(&w13)) && w13) {
    ComPtr<ICoreWebView2Profile> profile;
    if (SUCCEEDED(w13->get_Profile(&profile)) && profile) {
      profile->put_PreferredColorScheme(
          COREWEBVIEW2_PREFERRED_COLOR_SCHEME_LIGHT);
    }
  }

  std::shared_ptr<bool> alive = alive_;
  EventRegistrationToken tok{};

  // ---- halaman diklik/difokus: popup Flutter yang terbuka ikut ditutup
  // (klik di jendela native tidak sampai ke TapRegion Flutter)
  ctl->add_GotFocus(
      Callback<ICoreWebView2FocusChangedEventHandler>(
          [this, alive, id](ICoreWebView2Controller*, IUnknown*) -> HRESULT {
            if (!*alive) return S_OK;
            Emit(id, "focus", EncodableMap());
            return S_OK;
          })
          .Get(),
      &tok);

  // ---- popup: selalu jadi navigasi halaman utama (tanpa jendela kedua)
  v->webview->add_NewWindowRequested(
      Callback<ICoreWebView2NewWindowRequestedEventHandler>(
          [this, alive, id](ICoreWebView2* sender,
                            ICoreWebView2NewWindowRequestedEventArgs* args)
              -> HRESULT {
            if (!*alive) return S_OK;
            LPWSTR uri = nullptr;
            args->get_Uri(&uri);
            std::string u = TakeUtf8(uri);
            args->put_Handled(TRUE);
            if (!u.empty() && u != "about:blank") {
              sender->Navigate(Wide(u).c_str());
            }
            EncodableMap f;
            f[EncodableValue("url")] = EncodableValue(u);
            Emit(id, "newWindow", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  v->webview->add_NavigationStarting(
      Callback<ICoreWebView2NavigationStartingEventHandler>(
          [this, alive, id](ICoreWebView2*,
                            ICoreWebView2NavigationStartingEventArgs* args)
              -> HRESULT {
            if (!*alive) return S_OK;
            LPWSTR uri = nullptr;
            args->get_Uri(&uri);
            EncodableMap f;
            f[EncodableValue("phase")] = EncodableValue("start");
            f[EncodableValue("url")] = EncodableValue(TakeUtf8(uri));
            Emit(id, "nav", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  v->webview->add_NavigationCompleted(
      Callback<ICoreWebView2NavigationCompletedEventHandler>(
          [this, alive, id](ICoreWebView2* sender,
                            ICoreWebView2NavigationCompletedEventArgs* args)
              -> HRESULT {
            if (!*alive) return S_OK;
            BOOL ok = FALSE;
            args->get_IsSuccess(&ok);
            COREWEBVIEW2_WEB_ERROR_STATUS st =
                COREWEBVIEW2_WEB_ERROR_STATUS_UNKNOWN;
            args->get_WebErrorStatus(&st);
            LPWSTR src = nullptr;
            sender->get_Source(&src);
            EncodableMap f;
            f[EncodableValue("phase")] = EncodableValue("done");
            f[EncodableValue("ok")] = EncodableValue(ok == TRUE);
            f[EncodableValue("error")] = EncodableValue(static_cast<int32_t>(st));
            f[EncodableValue("url")] = EncodableValue(TakeUtf8(src));
            Emit(id, "nav", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  v->webview->add_SourceChanged(
      Callback<ICoreWebView2SourceChangedEventHandler>(
          [this, alive, id](ICoreWebView2* sender,
                            ICoreWebView2SourceChangedEventArgs*) -> HRESULT {
            if (!*alive) return S_OK;
            LPWSTR src = nullptr;
            sender->get_Source(&src);
            EncodableMap f;
            f[EncodableValue("url")] = EncodableValue(TakeUtf8(src));
            Emit(id, "source", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  v->webview->add_DocumentTitleChanged(
      Callback<ICoreWebView2DocumentTitleChangedEventHandler>(
          [this, alive, id](ICoreWebView2* sender, IUnknown*) -> HRESULT {
            if (!*alive) return S_OK;
            LPWSTR t = nullptr;
            sender->get_DocumentTitle(&t);
            EncodableMap f;
            f[EncodableValue("title")] = EncodableValue(TakeUtf8(t));
            Emit(id, "title", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  v->webview->add_ProcessFailed(
      Callback<ICoreWebView2ProcessFailedEventHandler>(
          [this, alive, id](ICoreWebView2*,
                            ICoreWebView2ProcessFailedEventArgs* args)
              -> HRESULT {
            if (!*alive) return S_OK;
            COREWEBVIEW2_PROCESS_FAILED_KIND kind =
                COREWEBVIEW2_PROCESS_FAILED_KIND_BROWSER_PROCESS_EXITED;
            args->get_ProcessFailedKind(&kind);
            EncodableMap f;
            f[EncodableValue("kind")] = EncodableValue(static_cast<int32_t>(kind));
            Emit(id, "crash", std::move(f));
            return S_OK;
          })
          .Get(),
      &tok);

  ApplyBounds(v);
  SetVisible(v, v->visible);

  // init script dulu (dokumen pertama sudah lahir dgn stub window.open),
  // baru navigasi. Hasil create dikirim setelah navigasi dimulai.
  auto left = std::make_shared<size_t>(scripts.size());
  auto go = [this, alive, id, url, result]() {
    if (!*alive) return;
    View* vv = Find(id);
    if (!vv || !vv->webview) {
      result->Error("disposed", "webview dibuang sebelum siap");
      return;
    }
    if (!url.empty()) vv->webview->Navigate(url.c_str());
    result->Success(EncodableValue(id));
  };
  if (scripts.empty()) {
    go();
    return;
  }
  for (const auto& s : scripts) {
    const auto* js = std::get_if<std::string>(&s);
    HRESULT hr = v->webview->AddScriptToExecuteOnDocumentCreated(
        Wide(js ? *js : std::string()).c_str(),
        Callback<ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler>(
            [left, go](HRESULT, LPCWSTR) -> HRESULT {
              if (--(*left) == 0) go();
              return S_OK;
            })
            .Get());
    if (FAILED(hr) && --(*left) == 0) go();
  }
}

void WebHost::Dispose(int64_t id) {
  auto it = views_.find(id);
  if (it == views_.end()) return;
  std::unique_ptr<View> v = std::move(it->second);
  views_.erase(it);
  if (v->controller) v->controller->Close();
  v->webview = nullptr;
  v->controller = nullptr;
  v->env = nullptr;
  if (v->container && IsWindow(v->container)) DestroyWindow(v->container);
}

// ================================================================ tata letak
void WebHost::SetRect(int x, int y, int w, int h) {
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  rect_ = RECT{x, y, x + w, y + h};
  for (auto& kv : views_) ApplyBounds(kv.second.get());
}

void WebHost::ApplyBounds(View* v) {
  if (!v->container) return;
  const int w = rect_.right - rect_.left;
  const int h = rect_.bottom - rect_.top;
  SetWindowPos(v->container, HWND_TOP, rect_.left, rect_.top, w, h,
               SWP_NOACTIVATE);
  if (v->controller) {
    RECT b{0, 0, w, h};
    v->controller->put_Bounds(b);
  }
  // region tidak ikut ukuran jendela: hitung ulang (dilewati kalau sama)
  if (ApplyRegion(v) && backdrop_) InvalidateRect(backdrop_, nullptr, FALSE);
}

void WebHost::SetHoles(std::vector<RECT> holes, int radius) {
  if (radius < 0) radius = 0;
  // dipanggil sampai sekali per frame saat popup beranimasi
  if (radius == hole_radius_ && holes.size() == holes_.size()) {
    bool same = true;
    for (size_t i = 0; i < holes.size() && same; ++i) {
      same = EqualRect(&holes[i], &holes_[i]) != FALSE;
    }
    if (same) return;
  }
  holes_ = std::move(holes);
  hole_radius_ = radius;
  bool changed = false;
  for (auto& kv : views_) changed |= ApplyRegion(kv.second.get());
  // FlutterView (WS_CLIPSIBLINGS) baru boleh menggambar di lubang setelah
  // region berubah: minta gambar ulang supaya tidak ada sisa halaman
  if (changed && backdrop_) InvalidateRect(backdrop_, nullptr, FALSE);
}

bool WebHost::ApplyRegion(View* v) {
  if (!v->container) return false;
  const int w = rect_.right - rect_.left;
  const int h = rect_.bottom - rect_.top;
  const RECT box{0, 0, w, h};
  // lubang -> koordinat wadah. Tidak dipotong ke wadah: sudut bulatnya
  // harus tetap di tempat walau lubang menjorok keluar (RGN_DIFF yang
  // memotong). Lubang yang sama sekali di luar wadah dibuang.
  std::vector<int> key;
  for (const RECT& hole : holes_) {
    RECT local{hole.left - rect_.left, hole.top - rect_.top,
               hole.right - rect_.left, hole.bottom - rect_.top};
    RECT clip;
    if (!IntersectRect(&clip, &local, &box)) continue;
    if (key.empty()) {
      key.push_back(w);
      key.push_back(h);
      key.push_back(hole_radius_);
    }
    key.push_back(local.left);
    key.push_back(local.top);
    key.push_back(local.right);
    key.push_back(local.bottom);
  }
  if (key == v->region_key) return false;

  if (key.empty()) {
    SetWindowRgn(v->container, nullptr, TRUE);
    v->region_key.clear();
    return true;
  }
  HRGN rgn = CreateRectRgn(0, 0, w, h);
  if (!rgn) return false;
  for (size_t i = 3; i + 3 < key.size(); i += 4) {
    const int l = key[i], t = key[i + 1], r = key[i + 2], b = key[i + 3];
    // jari-jari tak boleh lebih dari setengah sisi terpendek
    int rad = hole_radius_;
    if (rad > (r - l) / 2) rad = (r - l) / 2;
    if (rad > (b - t) / 2) rad = (b - t) / 2;
    // CreateRoundRectRgn: region-nya 1 piksel lebih pendek di kanan/bawah
    // dibanding CreateRectRgn (maka +1), dan dua argumen terakhir =
    // lebar/tinggi elips sudut = diameter (2 x jari-jari)
    HRGN cut = rad > 0
                   ? CreateRoundRectRgn(l, t, r + 1, b + 1, 2 * rad, 2 * rad)
                   : CreateRectRgn(l, t, r, b);
    if (!cut) continue;
    CombineRgn(rgn, rgn, cut, RGN_DIFF);
    DeleteObject(cut);
  }
  // berhasil = region jadi milik sistem (jangan dihapus); gagal = milik kita
  if (!SetWindowRgn(v->container, rgn, TRUE)) {
    DeleteObject(rgn);
    return false;
  }
  v->region_key = std::move(key);
  return true;
}

void WebHost::SetVisible(View* v, bool on) {
  v->visible = on;
  if (v->controller) v->controller->put_IsVisible(on ? TRUE : FALSE);
  if (on) {
    SetWindowPos(v->container, HWND_TOP, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
  } else {
    ShowWindow(v->container, SW_HIDE);
  }
}

// ================================================================ jendela
void WebHost::OnActivate(bool active) {
  if (!active) {
    HWND f = GetFocus();
    had_focus_ = false;
    for (auto& kv : views_) {
      HWND c = kv.second->container;
      if (f && (f == c || IsChild(c, f))) had_focus_ = true;
    }
    return;
  }
  if (!had_focus_) return;
  for (auto& kv : views_) {
    View* v = kv.second.get();
    if (v->visible && v->controller) {
      v->controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
      break;
    }
  }
}

void WebHost::OnMove() {
  for (auto& kv : views_) {
    if (kv.second->controller) {
      kv.second->controller->NotifyParentWindowPositionChanged();
    }
  }
}
