// TypingBot.exe pembawa (N6): satu exe yang membawa folder app v4 (zip)
// di ekornya. Dipakai sebagai aset rilis "TypingBot.exe" supaya:
//  - updater 3.5.x (ganti satu exe di tempatnya lalu jalankan) tetap jalan,
//  - unduhan baru cukup satu file.
// Alur: payload lebih baru dari %LOCALAPPDATA%\TypingBot\app\version.txt
// -> pasang (zip diekstrak tar.exe bawaan Windows ke app.new, lalu tukar),
// shortcut Start Menu diarahkan ke app\TypingBot.exe; lalu jalankan app.
// Argumen: --update --wait <pid>  (dipanggil v4 sendiri saat memperbarui:
// tunggu app lama tutup dulu).
//
// Format ekor file: [exe][zip][versi utf8][u32 panjang versi][u64 panjang zip]["TBBNDL01"]
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <objbase.h>
#include <shobjidl.h>
#include <string>
#include <vector>

static const char kMagic[8] = {'T', 'B', 'B', 'N', 'D', 'L', '0', '1'};

static std::wstring g_log;

static void Log(const std::wstring& s) { g_log += s + L"\r\n"; }

static std::wstring Env(const wchar_t* name) {
  wchar_t buf[MAX_PATH * 2];
  DWORD n = GetEnvironmentVariableW(name, buf, MAX_PATH * 2);
  return (n > 0 && n < MAX_PATH * 2) ? std::wstring(buf, n) : std::wstring();
}

static bool Exists(const std::wstring& p) {
  return GetFileAttributesW(p.c_str()) != INVALID_FILE_ATTRIBUTES;
}

static std::wstring Widen(const std::string& s) {
  if (s.empty()) return L"";
  int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
  std::wstring w(n, 0);
  MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &w[0], n);
  return w;
}

// "4.0.0-dev12" -> {4,0,0,12}; tanpa -dev = rilis (lebih tinggi dari dev mana pun)
static std::vector<long> ParseVer(const std::string& v) {
  std::vector<long> out;
  size_t i = 0;
  long cur = 0;
  bool any = false;
  for (; i < v.size() && v[i] != '-'; i++) {
    if (v[i] >= '0' && v[i] <= '9') {
      cur = cur * 10 + (v[i] - '0');
      any = true;
    } else if (v[i] == '.') {
      out.push_back(cur);
      cur = 0;
    }
  }
  if (any) out.push_back(cur);
  while (out.size() < 3) out.push_back(0);
  long dev = 0x7fffffff;
  size_t d = v.find("-dev");
  if (d != std::string::npos) {
    dev = 0;
    for (size_t k = d + 4; k < v.size() && v[k] >= '0' && v[k] <= '9'; k++) dev = dev * 10 + (v[k] - '0');
  }
  out.push_back(dev);
  return out;
}

static int CmpVer(const std::string& a, const std::string& b) {
  auto x = ParseVer(a), y = ParseVer(b);
  size_t n = x.size() > y.size() ? x.size() : y.size();
  for (size_t i = 0; i < n; i++) {
    long p = i < x.size() ? x[i] : 0, q = i < y.size() ? y[i] : 0;
    if (p != q) return p < q ? -1 : 1;
  }
  return 0;
}

static std::string ReadSmall(const std::wstring& path) {
  HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
  if (h == INVALID_HANDLE_VALUE) return "";
  char buf[256];
  DWORD got = 0;
  ReadFile(h, buf, sizeof(buf) - 1, &got, nullptr);
  CloseHandle(h);
  std::string s(buf, got);
  while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ')) s.pop_back();
  return s;
}

static bool WriteAll(const std::wstring& path, const void* data, size_t len) {
  HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
  if (h == INVALID_HANDLE_VALUE) return false;
  const char* p = (const char*)data;
  size_t left = len;
  bool ok = true;
  while (left > 0) {
    DWORD chunk = left > (1u << 24) ? (1u << 24) : (DWORD)left, wrote = 0;
    if (!WriteFile(h, p, chunk, &wrote, nullptr) || wrote == 0) {
      ok = false;
      break;
    }
    p += wrote;
    left -= wrote;
  }
  CloseHandle(h);
  return ok;
}

static void RemoveTree(const std::wstring& dir) {
  if (!Exists(dir)) return;
  std::wstring from = dir;
  from.push_back(L'\0');  // SHFileOperation butuh dua null
  SHFILEOPSTRUCTW op = {};
  op.wFunc = FO_DELETE;
  op.pFrom = from.c_str();
  op.fFlags = FOF_NO_UI;
  SHFileOperationW(&op);
}

struct Payload {
  std::vector<char> zip;
  std::string version;
};

static bool ReadPayload(const std::wstring& self, Payload& out) {
  HANDLE h = CreateFileW(self.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                         OPEN_EXISTING, 0, nullptr);
  if (h == INVALID_HANDLE_VALUE) return false;
  LARGE_INTEGER size;
  GetFileSizeEx(h, &size);
  bool ok = false;
  if (size.QuadPart > 20) {
    char tail[20];
    LARGE_INTEGER pos;
    pos.QuadPart = size.QuadPart - 20;
    DWORD got = 0;
    if (SetFilePointerEx(h, pos, nullptr, FILE_BEGIN) && ReadFile(h, tail, 20, &got, nullptr) && got == 20 &&
        memcmp(tail + 12, kMagic, 8) == 0) {
      UINT32 verLen;
      UINT64 zipLen;
      memcpy(&verLen, tail, 4);
      memcpy(&zipLen, tail + 4, 8);
      long long start = size.QuadPart - 20 - (long long)verLen - (long long)zipLen;
      if (verLen < 64 && start > 0) {
        out.zip.resize((size_t)zipLen);
        std::string ver(verLen, 0);
        pos.QuadPart = start;
        SetFilePointerEx(h, pos, nullptr, FILE_BEGIN);
        size_t left = (size_t)zipLen;
        char* p = out.zip.data();
        ok = true;
        while (left > 0) {
          DWORD chunk = left > (1u << 24) ? (1u << 24) : (DWORD)left;
          if (!ReadFile(h, p, chunk, &got, nullptr) || got == 0) {
            ok = false;
            break;
          }
          p += got;
          left -= got;
        }
        if (ok && verLen > 0) ok = ReadFile(h, &ver[0], verLen, &got, nullptr) && got == verLen;
        out.version = ver;
      }
    }
  }
  CloseHandle(h);
  return ok;
}

// ---------------------------------------------------------------- splash
static HWND g_splash = nullptr;

static LRESULT CALLBACK SplashProc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
  if (m == WM_PAINT) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(w, &ps);
    RECT r;
    GetClientRect(w, &r);
    HBRUSH bg = CreateSolidBrush(RGB(0x16, 0x18, 0x1d));
    FillRect(dc, &r, bg);
    DeleteObject(bg);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(0xe6, 0xe8, 0xee));
    HFONT f = CreateFontW(-18, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                          L"Segoe UI");
    HGDIOBJ old = SelectObject(dc, f);
    DrawTextW(dc, L"Memasang TypingBot...", -1, &r, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, old);
    DeleteObject(f);
    EndPaint(w, &ps);
    return 0;
  }
  return DefWindowProcW(w, m, wp, lp);
}

static void ShowSplash(HINSTANCE inst) {
  WNDCLASSW wc = {};
  wc.lpfnWndProc = SplashProc;
  wc.hInstance = inst;
  wc.lpszClassName = L"TypingBotSetupSplash";
  wc.hCursor = LoadCursor(nullptr, IDC_WAIT);
  wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(101));
  RegisterClassW(&wc);
  int w = 340, h = 96;
  int x = (GetSystemMetrics(SM_CXSCREEN) - w) / 2, y = (GetSystemMetrics(SM_CYSCREEN) - h) / 2;
  g_splash = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, wc.lpszClassName, L"TypingBot", WS_POPUP | WS_BORDER,
                             x, y, w, h, nullptr, nullptr, inst, nullptr);
  ShowWindow(g_splash, SW_SHOW);
  UpdateWindow(g_splash);
}

static void Pump() {
  MSG msg;
  while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
    TranslateMessage(&msg);
    DispatchMessageW(&msg);
  }
}

// tunggu proses sambil tetap memompa pesan (splash tidak 'Not responding')
static DWORD RunWait(std::wstring cmd, DWORD timeoutMs) {
  STARTUPINFOW si = {sizeof(si)};
  PROCESS_INFORMATION pi = {};
  if (!CreateProcessW(nullptr, &cmd[0], nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
    Log(L"gagal menjalankan: " + cmd);
    return (DWORD)-1;
  }
  DWORD start = GetTickCount();
  while (true) {
    DWORD r = MsgWaitForMultipleObjects(1, &pi.hProcess, FALSE, 200, QS_ALLINPUT);
    if (r == WAIT_OBJECT_0) break;
    Pump();
    if (GetTickCount() - start > timeoutMs) {
      TerminateProcess(pi.hProcess, 1);
      break;
    }
  }
  DWORD code = 1;
  GetExitCodeProcess(pi.hProcess, &code);
  CloseHandle(pi.hProcess);
  CloseHandle(pi.hThread);
  return code;
}

static void Shortcut(const std::wstring& target, const std::wstring& workdir) {
  std::wstring appdata = Env(L"APPDATA");
  if (appdata.empty()) return;
  std::wstring dir = appdata + L"\\Microsoft\\Windows\\Start Menu\\Programs";
  std::wstring lnk = dir + L"\\TypingBot.lnk";
  IShellLinkW* sl = nullptr;
  if (FAILED(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_IShellLinkW, (void**)&sl))) return;
  sl->SetPath(target.c_str());
  sl->SetWorkingDirectory(workdir.c_str());
  sl->SetIconLocation(target.c_str(), 0);
  IPersistFile* pf = nullptr;
  if (SUCCEEDED(sl->QueryInterface(IID_IPersistFile, (void**)&pf))) {
    pf->Save(lnk.c_str(), TRUE);
    pf->Release();
  }
  sl->Release();
}

static bool Launch(const std::wstring& exe, const std::wstring& dir) {
  std::wstring cmd = L"\"" + exe + L"\"";
  STARTUPINFOW si = {sizeof(si)};
  PROCESS_INFORMATION pi = {};
  if (!CreateProcessW(nullptr, &cmd[0], nullptr, nullptr, FALSE, 0, nullptr, dir.c_str(), &si, &pi)) return false;
  CloseHandle(pi.hProcess);
  CloseHandle(pi.hThread);
  return true;
}

static void Fail(const std::wstring& msg) {
  if (g_splash) DestroyWindow(g_splash);
  std::wstring base = Env(L"LOCALAPPDATA") + L"\\TypingBot";
  CreateDirectoryW(base.c_str(), nullptr);
  std::string u8;
  int n = WideCharToMultiByte(CP_UTF8, 0, g_log.c_str(), (int)g_log.size(), nullptr, 0, nullptr, nullptr);
  u8.resize(n);
  WideCharToMultiByte(CP_UTF8, 0, g_log.c_str(), (int)g_log.size(), &u8[0], n, nullptr, nullptr);
  WriteAll(base + L"\\setup.log", u8.data(), u8.size());
  if (Env(L"TB_SETUP_SILENT").empty()) MessageBoxW(nullptr, msg.c_str(), L"TypingBot", MB_OK | MB_ICONWARNING);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int) {
  int argc = 0;
  LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
  bool update = false;
  DWORD waitPid = 0;
  for (int i = 1; i < argc; i++) {
    std::wstring a = argv[i];
    if (a == L"--update") update = true;
    if (a == L"--wait" && i + 1 < argc) waitPid = (DWORD)_wtoi(argv[++i]);
  }

  HANDLE mutex = CreateMutexW(nullptr, TRUE, L"TypingBotSetupMutex");
  if (GetLastError() == ERROR_ALREADY_EXISTS) {
    WaitForSingleObject(mutex, 60000);  // pemasang lain sedang jalan: tunggu selesai
  }

  wchar_t selfBuf[MAX_PATH * 2];
  GetModuleFileNameW(nullptr, selfBuf, MAX_PATH * 2);
  std::wstring self = selfBuf;

  std::wstring local = Env(L"LOCALAPPDATA");
  if (local.empty()) {
    Fail(L"Folder LOCALAPPDATA tidak ditemukan.");
    return 1;
  }
  std::wstring base = local + L"\\TypingBot";
  std::wstring app = base + L"\\app";
  std::wstring appExe = app + L"\\TypingBot.exe";
  CreateDirectoryW(base.c_str(), nullptr);

  Payload p;
  if (!ReadPayload(self, p)) {
    // tanpa payload (file rusak / bukan bundel): coba buka yang terpasang
    if (Exists(appExe) && Launch(appExe, app)) return 0;
    Fail(L"File TypingBot ini rusak. Unduh ulang dari halaman rilis ya.");
    return 1;
  }
  std::string installed = ReadSmall(app + L"\\version.txt");
  bool perlu = !Exists(appExe) || installed.empty() || CmpVer(p.version, installed) > 0;
  Log(L"payload " + Widen(p.version) + L", terpasang " + Widen(installed));

  if (perlu) {
    if (waitPid) {
      HANDLE ph = OpenProcess(SYNCHRONIZE, FALSE, waitPid);
      if (ph) {
        WaitForSingleObject(ph, 30000);
        CloseHandle(ph);
      }
    }
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ShowSplash(inst);
    Pump();

    std::wstring zip = base + L"\\app-payload.zip";
    std::wstring baru = base + L"\\app.new";
    std::wstring lama = base + L"\\app.old";
    RemoveTree(baru);
    RemoveTree(lama);
    if (!WriteAll(zip, p.zip.data(), p.zip.size())) {
      Fail(L"Gagal menulis file pemasangan. Pastikan disk tidak penuh.");
      return 1;
    }
    p.zip.clear();
    p.zip.shrink_to_fit();
    CreateDirectoryW(baru.c_str(), nullptr);
    std::wstring sys = Env(L"SystemRoot");
    std::wstring tar = (sys.empty() ? std::wstring(L"C:\\Windows") : sys) + L"\\System32\\tar.exe";
    DWORD code = RunWait(L"\"" + tar + L"\" -xf \"" + zip + L"\" -C \"" + baru + L"\"", 120000);
    DeleteFileW(zip.c_str());
    if (code != 0 || !Exists(baru + L"\\TypingBot.exe")) {
      Log(L"tar keluar " + std::to_wstring(code));
      RemoveTree(baru);
      Fail(L"Gagal membuka paket TypingBot. Coba jalankan lagi.");
      return 1;
    }
    WriteAll(baru + L"\\version.txt", p.version.data(), p.version.size());

    // tukar folder; app lama bisa terkunci sebentar (baru saja ditutup)
    bool tukar = true;
    if (Exists(app)) {
      tukar = false;
      for (int i = 0; i < 40 && !tukar; i++) {
        tukar = MoveFileExW(app.c_str(), lama.c_str(), 0) != 0;
        if (!tukar) {
          Pump();
          Sleep(250);
        }
      }
    }
    if (!tukar) {
      Log(L"app lama terkunci, error " + std::to_wstring(GetLastError()));
      RemoveTree(baru);
      Fail(L"TypingBot masih terbuka. Tutup dulu, lalu jalankan file ini lagi.");
      return 1;
    }
    if (!MoveFileExW(baru.c_str(), app.c_str(), 0)) {
      Log(L"gagal memindah app.new, error " + std::to_wstring(GetLastError()));
      if (Exists(lama)) MoveFileExW(lama.c_str(), app.c_str(), 0);
      Fail(L"Gagal memasang TypingBot. Coba jalankan lagi.");
      return 1;
    }
    RemoveTree(lama);
    Shortcut(appExe, app);
    if (g_splash) DestroyWindow(g_splash);
    CoUninitialize();
  }

  if (!Env(L"TB_SETUP_NO_LAUNCH").empty()) return 0;
  if (!Launch(appExe, app)) {
    Fail(L"TypingBot terpasang tapi gagal dibuka.");
    return 1;
  }
  ReleaseMutex(mutex);
  return 0;
}
