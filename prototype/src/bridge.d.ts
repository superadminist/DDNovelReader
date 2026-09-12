export const SCHEMA_VERSION: 1;

export interface BridgeError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface BridgeResponse<T> {
  schemaVersion: 1;
  ok: boolean;
  data: T;
  error: BridgeError | null;
}

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
  error: BridgeError | null;
}

export type DuplicateMode = "cancel" | "overwrite" | "reparse";

export interface ImportSelectionItem {
  itemId: string;
  name: string;
  format: string;
  sizeBytes: number;
  supported: boolean;
  large: boolean;
  duplicate: {
    exists: boolean;
    bookId: string;
    title: string;
  };
}

export interface ImportSelectionData {
  cancelled: boolean;
  selectionId: string;
  total: number;
  duplicateCount: number;
  largeFileCount: number;
  items: ImportSelectionItem[];
}

export interface ImportStartData {
  jobId: string;
  state: "queued";
}

export interface ImportCancelData {
  jobId: string;
  cancelRequested: boolean;
}

export interface ImportProgressEvent {
  schemaVersion: 1;
  jobId: string;
  phase: "item";
  completed: number;
  total: number;
  succeeded: number;
  failed: number;
  item: {
    index: number;
    name: string;
    status: "running" | "succeeded" | "failed";
    bookId: string;
  };
  error: BridgeError | null;
}

export interface ImportResultItem {
  name: string;
  status: "succeeded" | "failed";
  bookId: string;
  error: BridgeError | null;
}

export interface ImportFinishedEvent {
  schemaVersion: 1;
  jobId: string;
  state: "completed" | "cancelled";
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  lastImportedBookId: string;
  openAfterImportBookId: string;
  results: ImportResultItem[];
}

export interface ImportControls {
  selectFiles(): Promise<BridgeResponse<ImportSelectionData>>;
  startFileImport(input: {
    selectionId: string;
    confirmLargeFiles: boolean;
    duplicateMode: DuplicateMode;
  }): Promise<BridgeResponse<ImportStartData>>;
  startPasteImport(input: {
    title: string;
    text: string;
  }): Promise<BridgeResponse<ImportStartData>>;
  cancelImport(jobId: string): Promise<BridgeResponse<ImportCancelData>>;
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
  imports: ImportControls;
  onBridgeError(callback: (payload: string) => void): void;
  onWindowStateChanged(callback: (payload: string) => void): void;
  onImportProgress(callback: (event: ImportProgressEvent) => void): void;
  onImportFinished(callback: (event: ImportFinishedEvent) => void): void;
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
