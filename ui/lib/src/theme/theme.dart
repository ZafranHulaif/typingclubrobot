// Brand "ink + volt": tinta gelap + aksen lime listrik, lilac utk detail.
// Token warna, tipe & gerak M3 dikumpulkan di sini saja.
import 'package:material_ui/material_ui.dart';

abstract final class Brand {
  static const volt = Color(0xFFC8F25A);
  static const lilac = Color(0xFFB9A7FF);
  static const amber = Color(0xFFFFC46B);
  static const coral = Color(0xFFFF6B6B);
  static const ink = Color(0xFF0B0C10);
}

/// Token gerak M3 (m3.material.io/styles/motion).
abstract final class Motion {
  static const short = Duration(milliseconds: 150);
  static const medium = Duration(milliseconds: 300);
  static const long = Duration(milliseconds: 450);
  static const standard = Cubic(0.2, 0, 0, 1);
  static const emphasized = Curves.easeInOutCubicEmphasized;
  static const decelerate = Cubic(0.05, 0.7, 0.1, 1);
  static const accelerate = Cubic(0.3, 0, 0.8, 0.15);
}

const _scheme = ColorScheme(
  brightness: Brightness.dark,
  primary: Brand.volt,
  onPrimary: Color(0xFF141A06),
  primaryContainer: Color(0xFF283214),
  onPrimaryContainer: Color(0xFFDDF79A),
  secondary: Brand.lilac,
  onSecondary: Color(0xFF1D1440),
  secondaryContainer: Color(0xFF2A2350),
  onSecondaryContainer: Color(0xFFDCD3FF),
  tertiary: Brand.amber,
  onTertiary: Color(0xFF2B1C00),
  tertiaryContainer: Color(0xFF3B2A0A),
  onTertiaryContainer: Color(0xFFFFDDA8),
  error: Brand.coral,
  onError: Color(0xFF3A0607),
  errorContainer: Color(0xFF3A1618),
  onErrorContainer: Color(0xFFFFC9C5),
  surface: Brand.ink,
  onSurface: Color(0xFFECEEF2),
  onSurfaceVariant: Color(0xFF9AA0AC),
  surfaceContainerLowest: Color(0xFF07080B),
  surfaceContainerLow: Color(0xFF101217),
  surfaceContainer: Color(0xFF14161C),
  surfaceContainerHigh: Color(0xFF1A1D24),
  surfaceContainerHighest: Color(0xFF22252D),
  outline: Color(0xFF3A3F4A),
  outlineVariant: Color(0xFF252830),
  inverseSurface: Color(0xFFECEEF2),
  onInverseSurface: Color(0xFF14161C),
  inversePrimary: Color(0xFF4F6A12),
  shadow: Colors.black,
  scrim: Colors.black,
);

TextStyle _f(String family, double size, double weight,
    {double height = 1.3, double spacing = 0}) {
  return TextStyle(
    fontFamily: family,
    fontSize: size,
    height: height,
    letterSpacing: spacing,
    fontWeight: FontWeight.values[((weight / 100).round() - 1).clamp(0, 8)],
    // font variabel: berat lewat sumbu wght
    fontVariations: [FontVariation('wght', weight)],
  );
}

const _display = 'Jakarta';
const _body = 'Inter';

final _text = TextTheme(
  displayLarge: _f(_display, 52, 750, height: 1.05, spacing: -1.5),
  displayMedium: _f(_display, 40, 750, height: 1.08, spacing: -1.0),
  displaySmall: _f(_display, 32, 700, height: 1.1, spacing: -0.6),
  headlineMedium: _f(_display, 24, 700, height: 1.2, spacing: -0.3),
  headlineSmall: _f(_display, 20, 700, height: 1.25, spacing: -0.2),
  titleLarge: _f(_display, 18, 650, height: 1.3, spacing: -0.1),
  titleMedium: _f(_display, 15, 650, height: 1.3),
  titleSmall: _f(_body, 13, 600, height: 1.35),
  bodyLarge: _f(_body, 15, 400, height: 1.5),
  bodyMedium: _f(_body, 13.5, 400, height: 1.45),
  bodySmall: _f(_body, 12, 400, height: 1.4),
  labelLarge: _f(_body, 13.5, 600, height: 1.2),
  labelMedium: _f(_body, 12, 550, height: 1.2, spacing: 0.1),
  labelSmall: _f(_body, 11, 600, height: 1.2, spacing: 0.4),
);

ThemeData buildTheme() {
  final s = _scheme;
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(14));
  return ThemeData(
    useMaterial3: true,
    colorScheme: s,
    scaffoldBackgroundColor: s.surface,
    fontFamily: _body,
    textTheme: _text.apply(bodyColor: s.onSurface, displayColor: s.onSurface),
    visualDensity: VisualDensity.standard,
    splashFactory: InkSparkle.splashFactory,
    dividerTheme: DividerThemeData(color: s.outlineVariant, space: 1),
    tooltipTheme: TooltipThemeData(
      waitDuration: const Duration(milliseconds: 450),
      decoration: BoxDecoration(
          color: s.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: s.outline)),
      textStyle: _text.bodySmall!.copyWith(color: s.onSurface),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        shape: shape,
        textStyle: _text.labelLarge,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 18),
        shape: shape,
        side: BorderSide(color: s.outline),
        foregroundColor: s.onSurface,
        textStyle: _text.labelLarge,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(0, 40),
        shape: shape,
        textStyle: _text.labelLarge,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: s.onSurfaceVariant),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: s.surfaceContainerHigh,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: s.outlineVariant)),
      enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: s.outlineVariant)),
      focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: s.primary, width: 1.5)),
      labelStyle: _text.bodyMedium!.copyWith(color: s.onSurfaceVariant),
      hintStyle: _text.bodyMedium!.copyWith(color: s.onSurfaceVariant),
    ),
    sliderTheme: SliderThemeData(
      trackHeight: 6,
      activeTrackColor: s.primary,
      inactiveTrackColor: s.surfaceContainerHighest,
      thumbColor: s.primary,
      overlayColor: s.primary.withValues(alpha: 0.12),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((st) =>
          st.contains(WidgetState.selected) ? s.onPrimary : s.outline),
      trackColor: WidgetStateProperty.resolveWith((st) =>
          st.contains(WidgetState.selected)
              ? s.primary
              : s.surfaceContainerHighest),
      trackOutlineColor: WidgetStateProperty.resolveWith((st) =>
          st.contains(WidgetState.selected) ? s.primary : s.outline),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        selectedBackgroundColor: s.primaryContainer,
        selectedForegroundColor: s.onPrimaryContainer,
        side: BorderSide(color: s.outlineVariant),
        textStyle: _text.labelMedium,
      ),
    ),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.windows: FadeForwardsPageTransitionsBuilder(),
      TargetPlatform.linux: FadeForwardsPageTransitionsBuilder(),
      TargetPlatform.macOS: FadeForwardsPageTransitionsBuilder(),
    }),
  );
}
