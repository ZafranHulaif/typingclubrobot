"""Modul kompatibilitas: engine kini paket engine/. GUI dan uji
tetap memakai `import autopilot_pw`; baca variabel diteruskan ke
state/config/jstemplates, tulis variabel selalu ke state."""
import sys
import types

from engine import config as _config
from engine import jstemplates as _jst
from engine import state as _state

from engine.hotkeys import (  # noqa: F401
    _cycle_speed,
    _hk_pause,
    _hk_speed,
    _hk_stop,
    _stop_bot,
    _toggle_pause,
)
from engine.browser import (  # noqa: F401
    _is_our_browser,
    _debug_address,
    _free_port,
    _browser_from_port_holder,
    _browser_running,
    _find_setup_tab,
    _check_debug_port,
    _exe_info_pid,
    _find_browser,
    _edclub_frame,
    _holder_identity,
    _is_edclub_url,
    _port_bind_free,
    _port_held_by_other_browser,
    _real_url,
    _restart_browser_debug,
    _run_hidden,
    _pick_port,
    _port_holders,
    _ask_close,
    _close_empty_tabs,
    connect,
    disconnect,
    set_confirmer,
    ensure_browser,
)
from engine.profiles import (  # noqa: F401
    _list_profiles,
    _proc_by_name,
    _close_user_browser,
    _user_data_dir,
    _profile_dir_arg,
)
from engine.jsutil import (  # noqa: F401
    _edclub_frames,
    all_frames,
    close_overlays_all_frames,
    detect_all_frames,
    dump_debug_info,
    frame_label,
    run_js,
)
from engine.typing_core import (  # noqa: F401
    _char_delay,
    _clear_modifiers,
    _mark_bot_click,
    _wait_for_user,
    _user_active,
    _user_idle_again,
    advance_score_screen,
    count_errors,
    esc_modals_only,
    focus_frame,
    keep_alive_frames,
    keep_alive_quiet,
    press_enter_guarded,
    read_remaining,
    read_state,
    type_chars,
)
from engine.lessons.standard import (  # noqa: F401
    handle_standard,
)
from engine.lessons.tutorial import (  # noqa: F401
    _tut_read,
    handle_tutorial,
)
from engine.lessons.games import (  # noqa: F401
    _phaser_try_advance,
    _premium_modal_action,
    handle_minigame,
    handle_phaser_minigame,
)
from engine.lessons.holdkey import (  # noqa: F401
    map_hold_key,
    try_hold_level,
)
from engine.lessons.screenkey import (  # noqa: F401
    click_screen_keyboard,
)
from engine.lessons.video import (  # noqa: F401
    handle_video_level,
)
from engine.lessons.intro import (  # noqa: F401
    _click_labeled_key,
    handle_intro_steps,
)
from engine.lessons.ocr import (  # noqa: F401
    ocr_words_from_frame,
    try_ocr_minigame,
)
from engine.recovery import (  # noqa: F401
    _finish_recovery,
    _switch_to_playable_tab,
    recover_and_restart_lesson,
)
from engine.levels import (  # noqa: F401
    _read_unlock_set,
    _goto_level_url,
    _goto_next_lesson_in_list,
    _lesson_id,
    _level_label,
    _record_level_map,
    _load_level_map,
    _range_validate_step,
    _skip_to_next_lesson,
    _wait_play_url,
    build_level_map,
    url_to_level,
)
from engine.session import (  # noqa: F401
    _fetch_login,
    _page_alive,
    _install_login_sentinel,
    _login_patrol,
    _probe_tab_login,
    _login_profile,
    _recover_renderer,
    _sweep_stripe_tabs,
)
from engine.rentang import (  # noqa: F401
    _range_check,
)
from engine.supervisor import (  # noqa: F401
    main_loop,
)


from engine import browser as _m_browser
from engine import hotkeys as _m_hotkeys
from engine import jsutil as _m_jsutil
from engine import levels as _m_levels
from engine import profiles as _m_profiles
from engine import recovery as _m_recovery
from engine import rentang as _m_rentang
from engine import session as _m_session
from engine import supervisor as _m_supervisor
from engine import typing_core as _m_typing
from engine.lessons import games as _m_games
from engine.lessons import holdkey as _m_holdkey
from engine.lessons import intro as _m_intro
from engine.lessons import ocr as _m_ocr
from engine.lessons import screenkey as _m_screenkey
from engine.lessons import standard as _m_standard
from engine.lessons import tutorial as _m_tutorial
from engine.lessons import video as _m_video

# Pemetaan nama -> modul PEMILIKnya. Patch atribut lewat modul ini harus
# terlihat oleh pemanggil internal (semua panggilan lintas modul engine
# memakai gaya atribut modul, jadi patch modul pemilik selalu efektif).
_OWNER = {}
for _m in (_state, _config, _jst, _m_browser, _m_hotkeys, _m_jsutil,
           _m_levels, _m_profiles, _m_recovery, _m_rentang, _m_session,
           _m_supervisor, _m_typing, _m_games, _m_holdkey, _m_intro,
           _m_ocr, _m_screenkey, _m_standard, _m_tutorial, _m_video):
    for _n in dir(_m):
        _OWNER.setdefault(_n, _m)


class _Shim(types.ModuleType):
    def __getattr__(self, name):
        m = _OWNER.get(name)
        if m is not None and hasattr(m, name):
            return getattr(m, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        setattr(_OWNER.get(name, _state), name, value)


sys.modules[__name__].__class__ = _Shim

if __name__ == "__main__":
    main_loop()
