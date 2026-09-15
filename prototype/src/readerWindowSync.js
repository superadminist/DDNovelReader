export function windowContainsSentence(windowData, sentence) {
  return Boolean(windowData && sentence
    && windowData.chapterIndex === sentence.chapterIndex
    && sentence.startOffset >= windowData.windowStartOffset
    && sentence.startOffset < windowData.windowEndOffset);
}

export function shouldApplyAudioWindow(requestId, latestRequestId, requestedSentence, latestPlayback, windowData) {
  const current = latestPlayback?.sentence;
  return requestId === latestRequestId
    && current?.chapterIndex === requestedSentence.chapterIndex
    && current?.startOffset === requestedSentence.startOffset
    && windowContainsSentence(windowData, current);
}
