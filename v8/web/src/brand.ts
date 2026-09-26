// The product brand for the SPA — a MIRROR of `edp8/brand.py` (design-e963c656f5 §4.12), the one
// constant every user-facing surface reads. `v8/tests/test_brand.py` fails if the two drift.
export const PRODUCT_NAME = "Heronry";
export const CLI_NAME = "heronry";
export const DESKTOP_APP_NAME = "Heronry Desktop";
export const TAGLINE = "your agent team, built on decisions, checked before delivery";

/** The 64 px app icon, served from web/public/brand (make_icons.py copies it there). */
export const LOGO_URL = `${import.meta.env.BASE_URL}brand/heronry-64.png`;
