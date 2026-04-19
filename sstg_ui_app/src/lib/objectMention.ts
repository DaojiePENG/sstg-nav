/**
 * 导航模式记忆触发：从用户文本中识别是否提及物品
 * 策略：① 已知词表子串命中 → hit；② 否则正则抽候选 → miss；③ 都不中 → none。
 */

export type MentionResult =
  | { kind: 'hit'; target: string }
  | { kind: 'miss'; target: string }
  | { kind: 'none' };

const STOP_WORDS = new Set<string>([
  '东西', '什么', '地方', '时候', '记忆', '印象', '这里', '那里',
  '房间', '现在', '刚才', '以前', '最近', '哪里', '任何', '一点',
  '样子', '怎么', '问题', '办法', '事情', '时间',
]);

const EXTRACT_PATTERNS: RegExp[] = [
  /我的([^\s，。！？,.!?]{1,8}?)(?:在|呢|吗|放|去|不见|丢)/,
  /([^\s，。！？,.!?]{1,8}?)(?:在哪|放哪|去哪|不见了?|丢了|找不到)/,
  /(?:看到|记得|瞧见|见过).{0,3}?([^\s，。！？,.!?]{1,8}?)(?:吗|了|没)/,
  /(?:找|寻找|找一下|找找)(?:我的|一个|一下)?([^\s，。！？,.!?]{1,8}?)(?:在|呢|吗|$)/,
];

function tidy(raw: string): string {
  return raw.replace(/^(?:的|了|那|这|个|一个|一下|一点|帮我|帮|给我|给)+/, '')
            .replace(/(?:的|了|吧|呢|啊|啦)+$/, '')
            .trim();
}

/** 词表子串匹配 —— 取最长命中的词（避免短词优先吞掉长词） */
function vocabHit(text: string, vocab: string[]): string | null {
  let best: string | null = null;
  for (const w of vocab) {
    if (!w || w.length < 1) continue;
    if (text.includes(w)) {
      if (!best || w.length > best.length) best = w;
    }
  }
  return best;
}

export function detectObjectMention(text: string, vocab: string[]): MentionResult {
  const src = (text || '').trim();
  if (src.length < 2) return { kind: 'none' };

  const hit = vocabHit(src, vocab);
  if (hit) return { kind: 'hit', target: hit };

  for (const p of EXTRACT_PATTERNS) {
    const m = src.match(p);
    if (!m?.[1]) continue;
    const cand = tidy(m[1]);
    if (cand.length < 2 || cand.length > 8) continue;
    if (STOP_WORDS.has(cand)) continue;
    // 常见副词/动词误抽过滤
    if (/^(要|想|来|去|叫|让|说|看|听|是|的|在|给|拿|就)/.test(cand)) continue;
    return { kind: 'miss', target: cand };
  }
  return { kind: 'none' };
}

/** 拉取已知物品词表（30s 本地缓存） */
let vocabCache: { value: string[]; fetchedAt: number } | null = null;
export async function fetchKnownObjectVocab(force = false): Promise<string[]> {
  const now = Date.now();
  if (!force && vocabCache && now - vocabCache.fetchedAt < 30_000) {
    return vocabCache.value;
  }
  try {
    const res = await fetch('/api/topo/vocab');
    if (!res.ok) return vocabCache?.value || [];
    const body = await res.json();
    const value: string[] = Array.isArray(body?.vocab) ? body.vocab : [];
    vocabCache = { value, fetchedAt: now };
    return value;
  } catch {
    return vocabCache?.value || [];
  }
}
