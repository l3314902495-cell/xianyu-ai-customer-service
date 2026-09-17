import type { Config } from "tailwindcss";
export default { content: ["./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"], theme: { extend: { colors: { brand: { DEFAULT: "#f5b700", dark: "#d99a00" } } } }, plugins: [] } satisfies Config;
