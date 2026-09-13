// Muted branch palette matching the reference mind-map style.
export const BRANCH_COLORS = [
  "#8B9E6F", // 橄榄绿
  "#CF7465", // 珊瑚红
  "#DAB16D", // 暖金色
  "#738BBC", // 灰蓝色
  "#9F80B2", // 雾紫色
  "#79A39A", // 灰青色
  "#C28B9E", // 藕粉色
  "#8B9FBF", // 钢蓝色
  "#C58E63", // 陶土色
  "#829A78", // 鼠尾草绿
];

export interface ThemeColors {
  root: {
    fontSize: number;
    fontWeight: number;
    fontFamily: string;
    paddingH: number;
    paddingV: number;
    bgColor: string;
    textColor: string;
  };
  node: {
    fontSize: number;
    fontWeight: number;
    fontFamily: string;
    paddingH: number;
    paddingV: number;
    textColor: string;
  };
  level1: {
    fontSize: number;
    fontWeight: number;
    paddingH: number;
    paddingV: number;
  };
  connection: {
    strokeWidth: number;
  };
  layout: {
    horizontalGap: number;
    verticalGap: number;
  };
  canvas: {
    bgColor: string;
  };
  controls: {
    bgColor: string;
    textColor: string;
    hoverBg: string;
    activeBg: string;
  };
  contextMenu: {
    bgColor: string;
    textColor: string;
    hoverBg: string;
    borderColor: string;
    shadowColor: string;
  };
  addBtn: {
    fill: string;
    hoverFill: string;
    iconColor: string;
  };
  selection: {
    strokeColor: string;
    fillColor: string;
  };
  highlight: {
    textColor: string;
    bgColor: string;
  };
}

const SHARED = {
  root: {
    fontSize: 40,
    fontWeight: 600,
    fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
    paddingH: 36,
    paddingV: 20,
  },
  node: {
    fontSize: 18,
    fontWeight: 400,
    fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
    paddingH: 8,
    paddingV: 6,
  },
  level1: {
    fontSize: 24,
    fontWeight: 500,
    paddingH: 18,
    paddingV: 9,
  },
  connection: {
    strokeWidth: 2.5,
  },
  layout: {
    horizontalGap: 80,
    verticalGap: 16,
  },
};

const LIGHT_THEME: ThemeColors = {
  ...SHARED,
  root: { ...SHARED.root, bgColor: "#3E4553", textColor: "#FFFFFF" },
  node: { ...SHARED.node, textColor: "#4B4B4B" },
  canvas: { bgColor: "#FFFFFF" },
  controls: {
    bgColor: "rgba(255, 255, 255, 0.9)",
    textColor: "#555",
    hoverBg: "rgba(0, 0, 0, 0.08)",
    activeBg: "rgba(0, 0, 0, 0.08)",
  },
  contextMenu: {
    bgColor: "rgba(255, 255, 255, 0.95)",
    textColor: "#333",
    hoverBg: "rgba(0, 0, 0, 0.06)",
    borderColor: "rgba(0, 0, 0, 0.08)",
    shadowColor: "rgba(0, 0, 0, 0.15)",
  },
  addBtn: {
    fill: "rgba(200, 200, 220, 0.6)",
    hoverFill: "rgba(180, 180, 200, 0.8)",
    iconColor: "#666",
  },
  selection: {
    strokeColor: "#4A90D9",
    fillColor: "rgba(74, 144, 217, 0.08)",
  },
  highlight: {
    textColor: "#fac800", // amber-800
    bgColor: "rgba(252, 211, 77, 0.2)", // amber-300/40
  },
};

const DARK_THEME: ThemeColors = {
  ...SHARED,
  root: { ...SHARED.root, bgColor: "#4A6FA5", textColor: "#FFFFFF" },
  node: { ...SHARED.node, textColor: "#E0E0E0" },
  canvas: { bgColor: "#1a1a2e" },
  controls: {
    bgColor: "rgba(30, 30, 45, 0.9)",
    textColor: "#ccc",
    hoverBg: "rgba(255, 255, 255, 0.1)",
    activeBg: "rgba(255, 255, 255, 0.12)",
  },
  contextMenu: {
    bgColor: "rgba(35, 35, 50, 0.95)",
    textColor: "#ddd",
    hoverBg: "rgba(255, 255, 255, 0.08)",
    borderColor: "rgba(255, 255, 255, 0.1)",
    shadowColor: "rgba(0, 0, 0, 0.4)",
  },
  addBtn: {
    fill: "rgba(100, 100, 130, 0.6)",
    hoverFill: "rgba(120, 120, 150, 0.8)",
    iconColor: "#aaa",
  },
  selection: {
    strokeColor: "#5B9BD5",
    fillColor: "rgba(91, 155, 213, 0.15)",
  },
  highlight: {
    textColor: "#fcd34d", // amber-300
    bgColor: "rgba(251, 191, 36, 0.2)", // amber-400/20
  },
};

export function getTheme(mode: "light" | "dark"): ThemeColors {
  return mode === "dark" ? DARK_THEME : LIGHT_THEME;
}

// The reference palette uses dark text on the olive and gold cards, and light
// text on the remaining first-level branch colors.
const LEVEL1_TEXT_COLORS = [
  "#20291A",
  "#FFFFFF",
  "#242016",
  "#FFFFFF",
  "#FFFFFF",
  "#FFFFFF",
  "#20291A",
  "#FFFFFF",
  "#242016",
  "#FFFFFF",
];

function getFallbackLevel1TextColor(color: string): string {
  const match = color.trim().match(/^#([0-9a-f]{6})$/i);
  if (!match) return "#FFFFFF";

  const channels = [0, 2, 4].map((offset) => {
    const value = parseInt(match[1].slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045
      ? value / 12.92
      : Math.pow((value + 0.055) / 1.055, 2.4);
  });
  const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  return luminance > 0.42 ? "#242016" : "#FFFFFF";
}

export function getLevel1TextColor(color: string, branchIndex?: number): string {
  const paletteColor = branchIndex === undefined
    ? undefined
    : BRANCH_COLORS[branchIndex % BRANCH_COLORS.length];
  if (paletteColor?.toLowerCase() === color.trim().toLowerCase()) {
    return LEVEL1_TEXT_COLORS[branchIndex! % LEVEL1_TEXT_COLORS.length];
  }
  return getFallbackLevel1TextColor(color);
}

// Backward compatible default export
export const THEME = LIGHT_THEME;

/**
 * Generate CSS custom properties from theme for the container element.
 * Users can override these to customize the mind map appearance.
 */
export function generateCSSVariables(
  theme: ThemeColors,
  branchColors: string[] = BRANCH_COLORS,
): Record<string, string> {
  const vars: Record<string, string> = {
    '--mindmap-canvas-bg': theme.canvas.bgColor,
    '--mindmap-root-bg': theme.root.bgColor,
    '--mindmap-root-text': theme.root.textColor,
    '--mindmap-root-font-size': `${theme.root.fontSize}px`,
    '--mindmap-root-font-weight': String(theme.root.fontWeight),
    '--mindmap-root-font-family': theme.root.fontFamily,
    '--mindmap-node-text': theme.node.textColor,
    '--mindmap-node-font-size': `${theme.node.fontSize}px`,
    '--mindmap-node-font-weight': String(theme.node.fontWeight),
    '--mindmap-node-font-family': theme.node.fontFamily,
    '--mindmap-level1-font-size': `${theme.level1.fontSize}px`,
    '--mindmap-level1-font-weight': String(theme.level1.fontWeight),
    '--mindmap-edge-width': String(theme.connection.strokeWidth),
    '--mindmap-selection-stroke': theme.selection.strokeColor,
    '--mindmap-selection-fill': theme.selection.fillColor,
    '--mindmap-highlight-text': theme.highlight.textColor,
    '--mindmap-highlight-bg': theme.highlight.bgColor,
    '--mindmap-addbtn-fill': theme.addBtn.fill,
    '--mindmap-addbtn-hover': theme.addBtn.hoverFill,
    '--mindmap-addbtn-icon': theme.addBtn.iconColor,
    '--mindmap-controls-bg': theme.controls.bgColor,
    '--mindmap-controls-text': theme.controls.textColor,
    '--mindmap-controls-hover': theme.controls.hoverBg,
    '--mindmap-ctx-bg': theme.contextMenu.bgColor,
    '--mindmap-ctx-text': theme.contextMenu.textColor,
    '--mindmap-ctx-hover': theme.contextMenu.hoverBg,
    '--mindmap-ctx-border': theme.contextMenu.borderColor,
    '--mindmap-ctx-shadow': theme.contextMenu.shadowColor,
  };
  for (let i = 0; i < branchColors.length; i++) {
    vars[`--mindmap-branch-${i}`] = branchColors[i];
  }
  return vars;
}

/**
 * Generate a CSS style string with resolved values for SVG export.
 * Uses concrete values (not CSS variables) for maximum compatibility.
 */
export function generateExportStyles(theme: ThemeColors): string {
  return [
    `.mindmap-edge { stroke-width: ${theme.connection.strokeWidth}; stroke-linecap: round; fill: none; }`,
    `.mindmap-node-underline { stroke-width: 2.5; stroke-linecap: round; }`,
    `.mindmap-code-bg { fill: rgba(128,128,128,0.12); }`,
    `.mindmap-highlight-bg { fill: ${theme.highlight.bgColor}; }`,
    `.mindmap-edge-label { pointer-events: none; font-family: ${theme.node.fontFamily}; }`,
  ].join('\n    ');
}
