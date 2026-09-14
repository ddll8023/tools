// Warm, muted branch colors that stay within the application's orange-neutral palette.
export const BRANCH_COLORS = [
  "#F5A623", // 品牌橙
  "#C87961", // 陶土红
  "#B18B52", // 柔和金
  "#82996F", // 鼠尾草绿
  "#778D9B", // 灰蓝
  "#9B82A8", // 雾紫
  "#C58B96", // 藕粉
  "#6F9893", // 灰青
  "#B57B5F", // 陶土
  "#9A9E6B", // 橄榄黄
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
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    paddingH: 36,
    paddingV: 20,
  },
  node: {
    fontSize: 18,
    fontWeight: 400,
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
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
  root: { ...SHARED.root, bgColor: "#F5A623", textColor: "#FFFFFF" },
  node: { ...SHARED.node, textColor: "#2D2D2D" },
  canvas: { bgColor: "#FAFAF8" },
  controls: {
    bgColor: "rgba(255, 255, 255, 0.96)",
    textColor: "#2D2D2D",
    hoverBg: "#F5F5F2",
    activeBg: "#FDEBD0",
  },
  contextMenu: {
    bgColor: "#FFFFFF",
    textColor: "#2D2D2D",
    hoverBg: "#F5F5F2",
    borderColor: "#EBEBE7",
    shadowColor: "rgba(45, 45, 45, 0.12)",
  },
  addBtn: {
    fill: "#FDEBD0",
    hoverFill: "#F5A623",
    iconColor: "#D4890A",
  },
  selection: {
    strokeColor: "#F5A623",
    fillColor: "rgba(245, 166, 35, 0.12)",
  },
  highlight: {
    textColor: "#D4890A",
    bgColor: "rgba(245, 166, 35, 0.18)",
  },
};

const DARK_THEME: ThemeColors = {
  ...SHARED,
  root: { ...SHARED.root, bgColor: "#D4890A", textColor: "#FFFFFF" },
  node: { ...SHARED.node, textColor: "#FAFAF8" },
  canvas: { bgColor: "#2D2D2D" },
  controls: {
    bgColor: "rgba(45, 45, 45, 0.96)",
    textColor: "#FAFAF8",
    hoverBg: "rgba(255, 255, 255, 0.08)",
    activeBg: "rgba(245, 166, 35, 0.22)",
  },
  contextMenu: {
    bgColor: "#353532",
    textColor: "#FAFAF8",
    hoverBg: "rgba(255, 255, 255, 0.08)",
    borderColor: "rgba(255, 255, 255, 0.16)",
    shadowColor: "rgba(0, 0, 0, 0.35)",
  },
  addBtn: {
    fill: "rgba(245, 166, 35, 0.22)",
    hoverFill: "rgba(245, 166, 35, 0.38)",
    iconColor: "#FDEBD0",
  },
  selection: {
    strokeColor: "#F5A623",
    fillColor: "rgba(245, 166, 35, 0.2)",
  },
  highlight: {
    textColor: "#FDEBD0",
    bgColor: "rgba(245, 166, 35, 0.22)",
  },
};

export function getTheme(mode: "light" | "dark"): ThemeColors {
  return mode === "dark" ? DARK_THEME : LIGHT_THEME;
}

// Keep first-level labels aligned with the application's dark text color.
const LEVEL1_TEXT_COLORS = BRANCH_COLORS.map(() => "#2D2D2D");

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
  return luminance > 0.42 ? "#2D2D2D" : "#FFFFFF";
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
    '--mindmap-controls-active': theme.controls.activeBg,
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
    `.mindmap-code-bg { fill: ${theme.controls.hoverBg}; }`,
    `.mindmap-highlight-bg { fill: ${theme.highlight.bgColor}; }`,
    `.mindmap-edge-label { pointer-events: none; font-family: ${theme.node.fontFamily}; }`,
  ].join('\n    ');
}
