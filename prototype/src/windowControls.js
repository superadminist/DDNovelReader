export function windowControlPresentation(windowState) {
  const isMaximized = Boolean(windowState?.isMaximized);
  return {
    isMaximized,
    maximizeLabel: isMaximized ? "还原窗口" : "最大化窗口",
    maximizeIcon: isMaximized ? "restore" : "maximize",
  };
}
