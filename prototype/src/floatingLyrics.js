export function floatingSentenceIdentity(sentence) {
  return sentence ? `${sentence.chapterIndex}:${sentence.startOffset}` : "empty";
}

export function compareFloatingSentences(previous, next) {
  if (!previous || !next) return "forward";
  if (next.chapterIndex !== previous.chapterIndex) {
    return next.chapterIndex > previous.chapterIndex ? "forward" : "backward";
  }
  return next.startOffset >= previous.startOffset ? "forward" : "backward";
}

export function floatingLyricTransition(previousContext, nextContext) {
  const previousIdentity = floatingSentenceIdentity(previousContext?.current);
  const nextIdentity = floatingSentenceIdentity(nextContext?.current);
  return {
    changed: previousIdentity !== nextIdentity,
    direction: compareFloatingSentences(previousContext?.current, nextContext?.current),
    previousIdentity,
    nextIdentity,
  };
}
