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

export interface ReaderPosition {
  chapterIndex: number;
  charOffset: number;
  progressPercent: number;
}

export interface ReaderChapterSummary {
  index: number;
  title: string;
  charCount: number;
}

export interface ReaderTextBlock {
  id: string;
  startOffset: number;
  endOffset: number;
  text: string;
  startsParagraph: boolean;
  endsParagraph: boolean;
}

export interface ReaderContentWindow {
  sessionId: string;
  bookId: string;
  chapterIndex: number;
  chapterTitle: string;
  chapterCharCount: number;
  anchorOffset: number;
  windowStartOffset: number;
  windowEndOffset: number;
  hasBefore: boolean;
  hasAfter: boolean;
  blocks: ReaderTextBlock[];
}

export interface ReaderSentence {
  chapterIndex: number;
  startOffset: number;
  endOffset: number;
  text: string;
}

export type PlaybackStatus = "idle" | "playing" | "paused" | "finished" | "error";

export interface ReaderPlaybackSnapshot {
  status: PlaybackStatus;
  position: ReaderPosition;
  sentence: ReaderSentence | null;
  requestedBackend: "sapi" | "edge";
  activeBackend: "sapi" | "edge" | null;
  fallbackActive: boolean;
}

export interface ReaderSettings {
  fontFamily: string;
  fontSize: number;
  lineSpacing: number;
  paragraphMode: 1 | 2 | 3;
  firstLineIndent: boolean;
  ttsRate: number;
  ttsVoiceId: string;
  volume: number;
  sentenceGapSeconds: number;
}

export interface ReaderOpenData {
  sessionId: string;
  book: {
    id: string;
    title: string;
    author: string;
    format: string;
    totalChars: number;
    chapters: ReaderChapterSummary[];
  };
  position: ReaderPosition;
  window: ReaderContentWindow;
  settings: ReaderSettings;
  playback: ReaderPlaybackSnapshot;
  bookmarkCount: number;
}

export interface ReaderOpenStartData {
  requestId: string;
  bookId: string;
  state: "loading";
}

export interface ReaderOpenedEvent {
  schemaVersion: 1;
  requestId: string;
  bookId: string;
  ok: boolean;
  data: ReaderOpenData | null;
  error: BridgeError | null;
}

export type ReaderNavigationTarget =
  | { kind: "position"; chapterIndex: number; charOffset: number }
  | { kind: "percent"; percent: number };

export interface ReaderNavigateData {
  position: ReaderPosition;
  window: ReaderContentWindow;
  playback: ReaderPlaybackSnapshot;
}

export interface ReaderPositionUpdateData {
  updated: boolean;
  position: ReaderPosition;
}

export interface ReaderSearchResult {
  id: string;
  chapterIndex: number;
  chapterTitle: string;
  startOffset: number;
  endOffset: number;
  excerptStartOffset: number;
  excerpt: string;
}

export interface ReaderSearchPage {
  query: string;
  total: number;
  nextCursor: string;
  results: ReaderSearchResult[];
}

export interface ReaderSearchStartData {
  requestId: string;
  state: "searching";
}

export interface ReaderSearchFinishedEvent {
  schemaVersion: 1;
  requestId: string;
  sessionId: string;
  ok: boolean;
  data: ReaderSearchPage | null;
  error: BridgeError | null;
}

export interface ReaderBookmark {
  id: string;
  chapterIndex: number;
  chapterTitle: string;
  startOffset: number;
  endOffset: number;
  text: string;
  note: string;
  createdAt: number;
}

export interface ReaderBookmarkPage {
  total: number;
  nextCursor: string;
  items: ReaderBookmark[];
}

export type ReaderPlaybackCommand =
  | "play"
  | "pause"
  | "stop"
  | "previousSentence"
  | "nextSentence";

export interface ReaderPlaybackCommandData {
  commandId: string;
  accepted: boolean;
}

export interface ReaderPlaybackEvent {
  schemaVersion: 1;
  sessionId: string;
  bookId: string;
  sequence: number;
  commandId: string;
  reason:
    | "state"
    | "sentenceStart"
    | "sentenceDone"
    | "finished"
    | "fallback"
    | "error";
  playback: ReaderPlaybackSnapshot;
  error: BridgeError | null;
}

export interface ReaderControls {
  openBook(bookId: string): Promise<BridgeResponse<ReaderOpenStartData>>;
  getWindow(input: {
    sessionId: string;
    chapterIndex: number;
    anchorOffset: number;
  }): Promise<BridgeResponse<ReaderContentWindow>>;
  navigate(input: {
    sessionId: string;
    target: ReaderNavigationTarget;
  }): Promise<BridgeResponse<ReaderNavigateData>>;
  updatePosition(input: {
    sessionId: string;
    chapterIndex: number;
    charOffset: number;
  }): Promise<BridgeResponse<ReaderPositionUpdateData>>;
  search(input: {
    sessionId: string;
    query: string;
    cursor: string;
  }): Promise<BridgeResponse<ReaderSearchStartData>>;
  listBookmarks(input: {
    sessionId: string;
    cursor: string;
  }): Promise<BridgeResponse<ReaderBookmarkPage>>;
  addBookmark(input: {
    sessionId: string;
    chapterIndex: number;
    startOffset: number;
    endOffset: number;
    note: string;
  }): Promise<BridgeResponse<ReaderBookmark>>;
  removeBookmark(input: {
    sessionId: string;
    bookmarkId: string;
  }): Promise<BridgeResponse<{ bookmarkId: string; removed: boolean }>>;
  controlPlayback(input: {
    sessionId: string;
    command: ReaderPlaybackCommand;
  }): Promise<BridgeResponse<ReaderPlaybackCommandData>>;
  updateSettings(input: {
    sessionId: string;
    patch: Partial<ReaderSettings>;
  }): Promise<BridgeResponse<ReaderSettings>>;
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
  reader: ReaderControls;
  onBridgeError(callback: (payload: string) => void): void;
  onWindowStateChanged(callback: (payload: string) => void): void;
  onImportProgress(callback: (event: ImportProgressEvent) => void): void;
  onImportFinished(callback: (event: ImportFinishedEvent) => void): void;
  onReaderOpened(callback: (event: ReaderOpenedEvent) => void): void;
  onReaderSearchFinished(callback: (event: ReaderSearchFinishedEvent) => void): void;
  onReaderPlaybackChanged(callback: (event: ReaderPlaybackEvent) => void): void;
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
