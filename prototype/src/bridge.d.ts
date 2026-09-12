export const SCHEMA_VERSION: 1;

export interface BookSummary {
  id: string;
  title: string;
  author: string;
  format: string;
  progressPercent: number;
  chapterIndex: number;
  chapterCount: number;
  currentChapterTitle: string;
  lastReadAt: number | null;
  totalChars: number;
  coverUrl: string;
}

export interface InitialStateData {
  library: { books: BookSummary[]; total: number };
  window: { isMaximized: boolean };
  capabilities: {
    fileImport: boolean;
    pasteImport: boolean;
    webImport: boolean;
    audioImport: boolean;
    reader: boolean;
    tts: boolean;
    floatingReader: boolean;
  };
}

export interface InitialStateResponse {
  schemaVersion: 1;
  ok: boolean;
  data: InitialStateData;
  error: { code: string; message: string; retryable: boolean } | null;
}

export interface WindowControls {
  minimizeWindow(): void;
  toggleMaximizeWindow(): void;
  closeWindow(): void;
  startWindowMove(): void;
  startWindowResize(edge: "top" | "right" | "bottom" | "left" | "topRight" | "bottomRight" | "bottomLeft" | "topLeft"): void;
}

export interface BridgeConnection {
  mode: "demo" | "native";
  initialState: InitialStateResponse;
  controls: WindowControls;
  onBridgeError(callback: (payload: string) => void): void;
  onWindowStateChanged(callback: (payload: string) => void): void;
  dispose(): void;
}

export class BridgeProtocolError extends Error {
  code: string;
  initialData: InitialStateData;
  connection?: BridgeConnection;
  constructor(message: string, code?: string, initialData?: InitialStateData);
}

export function createDemoInitialState(): InitialStateResponse;
export function parseInitialState(raw: string | InitialStateResponse): InitialStateResponse;
export function connectBridge(environment?: { window?: Window; document?: Document }): Promise<BridgeConnection>;
