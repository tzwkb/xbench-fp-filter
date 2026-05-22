import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any
from openai import AsyncOpenAI

import config

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
    return _client

REVIEW_PROMPT = """你是游戏本地化翻译质检复核专家。请判定以下 QA 初检结果是否正确。

【当前错误】
错误类型：{error_type}
错误描述：{error_description}
严重程度：{severity}
原文：{source_text}
译文：{target_text}
{note_block}
{similar_cases_block}

【判定方式】
默认判定为真错误。只有当前条目明确命中以下规则之一，才改判为误报。无法明确命中任何规则时，维持真错误。

【误报放行规则（需明确命中才能判误报）】
A. 代词/泛指替代：各类指代对象（含人物称谓、身份标识、事物主体、场所地点、机构群体、抽象概念等）在对话或叙述中被代词（you/he/she/they/it/this/that）或泛指（someone/our host/someone in charge/a man/the party/the relevant side）替代，只要不影响理解即可接受。包括但不限于：NPC对玩家的称呼、叙述中的第三人称指代、已建立身份/场景/主体的泛指、口语中的泛指替代。**A排除：① 术语表中含称谓前缀的固定专名（如「Big Feng」「Big Zhao」），省略或替换称谓前缀（如只译为「Feng」或「Brother Zhao」）不触发A——称谓前缀是规定译名的固定组成部分；② 有官方固定英文名的具名游戏实体（怪物/BOSS/特定构造体等），不得以代词或泛指描述替代（如「矩天踆乌/Sun Crow」不得替代为「her enemy」或「the great construct」）——具名实体名称不属于"不影响理解的指代"。**
B. 省略：当原文语境已明确铺垫相关信息（含场景背景、表述主体、限定条件、补充说明等），无需重复提及具体内容即可让读者清晰理解语义时，或因叙事焦点转移：地名/场所名是背景信息，译文聚焦事件/情感而省略地名，故事信息依旧完整时，可对原文中对应的显性内容进行省略处理。此类省略只要符合英文表达习惯、不产生语义歧义、不遗漏核心信息，**一律可接受**。**注意：① 术语中的功能性限定词（如 weapon、系列名、类型前缀等）不属于可省略的背景信息，省略后导致术语类别属性缺失的，不得触发规则 B；② 规则 B 仅适用于对应内容在译文中完全未提及的情形——若译文用不同词语表达了原文术语（如用"United Aspirations"表达"众志凌霄/Skyward Bond"），属术语翻译错误，不得以省略规则放行。**
C. 术语对应有误：满足以下任一情形即可触发：① error_description 中的检测中文词条，是术语表中另一个更长词条的子串，导致系统错误匹配了不相关词条；② 原文、规定译名、实际译文三者完全一致，属系统误匹配——**C②限制：规定译名为多词固定短语时（如「The Nine Mortal Ways Disciple」），译文将其拆分重排（如「a disciple of The Nine Mortal Ways」），三者并不完全一致，不触发C②**；③ 检测中文词条作为字符级子串出现在原文一个含义不同的更长复合词中，导致系统将该复合词误判为术语违规。此规则覆盖所有复合词类型，只要检测词在该复合词中不作为独立术语使用即可触发——名词复合：「势」在「形势」、「精气」在「精气神」；动词复合：「解」在「解锁」「解救」「解除」（解 ≠ Interpretation）；形容词复合：「绝」在「绝世外观」（绝世 ≠ Annihilation）；颜色词：「紫」在「紫色」（紫色=颜色 ≠ Epic）、「明」在「夜明珠」「查明」；词素字：「极」在「蹦极」、「皮」在「皮影」、「水」在「山水」；人名字符：「钱」在人名「钱多多」（钱=姓氏 ≠ Coin）。**C③重要限制：判断时只能基于 error_description 中标注的检测词，不得将源文本中其他字符的复合词关系代入判断。例如：error_description 为「建造|Build」，则只检查「建造」是否嵌入含义不同的复合词——「建造」在「蹦极禁止建造区域」中是独立词汇，不嵌入任何复合词，C③不触发；源文本中恰好出现「蹦极」与「极」的关系和本条无关。C③排除：若检测词是一个完整专有名词（地名/角色名）的组成部分，且复合词只是在该专有名词后附加了类型词（如庄/村/馆等），则复合词中该术语含义未变，不得触发C③（例：「不见山」在「不见山庄」中，仍指不见山该地，非含义不同的复合词）。另，C规则仅针对检测机制本身的匹配错误，不用于论证"当前语境下该术语应有不同译法"——后者属真错误。注意：译文比规定译名包含更多词不属于超集误匹配——规定译名是标准上限，译文多词是真错误，不得触发规则 C。**
D. 术语应用语境有误：术语表词条有明确适用场景（含UI界面、任务系统、玩法说明、物品道具、角色名称等），但原文实际应用场景与词条规定场景不符，包括但不限于：技能分类命名、角色/武器/技能外观名称、系统功能说明等场景的术语，被应用于剧情对话；剧情内NPC名称/剧情相关场景名称/剧情相关道具名称，被应用于功法培养界面等。**典型示例：「紫/Epic」「紫色/Epic」是稀有度等级术语，但原文「紫色花卉」是颜色描述→语境不符；「多人/Multiplayer」是游戏功能术语，但原文「遇着太多人」是剧情叙事→语境不符；「主动/Active Skill」是技能分类术语，但原文「主动交互」是操作方式描述→语境不符。D排除：若检测词是角色/人物名称的组成字符，且该字符对应术语有明确英文译名（如鹏/Roc、鸿/Brant），不得以"人名语境"触发D——人名中含术语字符时，应以真错误处理，除非该角色的官方英文名已确认不含该术语译名。**
E. 合理同义替换：译文使用与规定译名语义等价的通用功能性词汇（如 defeat 替代 Kill、Single 替代 Solo）。**以下情形不得触发规则 E：① 专有名词、人名、地名、物品道具名、场所名、技能名等具名实体（此类术语有且仅有一个规定译名）；游戏操作指令词（如 跳跃/Jump → Leap 错误）、战斗状态词（如 受击/Hit Stagger → being staggered 错误）、数值加成词（如 增伤/DMG Boost → increase damage 错误）、游戏系统名词（如 幻境/Illusion → vision 错误、调查/Investigate → Inspect 错误）均属具名游戏术语，有且仅有一个规定译名，不得触发E；含称谓前缀的固定专名（如 Big Zhao → Brother Zhao 错误）中的称谓词是规定译名组成，替换称谓词不触发E；② 译文与规定译名的核心名词不同（如 Lantern Fair → Lantern Festival、Ash → Withered Bough）；③ 用通俗表达替换专业/官方术语（如 Face Blindness 替换 Prosopagnosia）；④ 译文比规定译名增减了有实义的词，包括有实义的限定词——如 Foreign Invader → invaders（省略了 Foreign）、Imperial Palace → Palace（省略了 Imperial），不得以"上下文已知"为由放行。**
F. 词形/格式差异：译文与规定译名仅存在以下纯语法曲折变化：同一词根的语法形态变化（Freezing vs Frozen）、缩写差异（level vs Lv.）、冠词增减（the）、单复数差异。**以下情形不得触发规则 F：① 专有名词的词序重排，例如「Yueniang's Notes」改写为「Notes from Yueniang」属词序重排，不得触发规则 F；② 增减有实义的修饰词（如加了 Imperial）；③ 作品名、歌曲名、篇章名等具名作品标题——此类专有名词的介词/冠词/缩写拼写是名称的固定组成部分，不属于纯语法形式差异（例：「Melody Amid Reeds」改为「Melody in the Reeds」、「Lotus O' Luck」改为「Lotus of Good Luck」均属标题变更，不得触发F）；④ 派生词形变化不触发F——F只适用于同一词根的曲折变化，不适用于词类转换（如 Target → Targeted 是名词→形容词的派生变化，含义有差，不得触发F）；⑤ 宗派/门派名+成员身份词构成的固定多词术语（如「Velvet Shade Disciple」「The Nine Mortal Ways Disciple」），将其改写为「a [身份词] of [宗派名]」句式（如「a disciple of the Velvet Shade」）属术语结构破坏，不触发F；⑥ 规定译名中含固定单/复数形式且该词是专有名称（技能名、宗派名等）的组成部分（如技能名中的 Cranes），单复数差异不触发F；⑦ 专有名词的汉语拼音连写/分写形式（如 Xiaoba vs Xiao Ba）是名称固定拼写，不属于纯语法差异，不触发F。**

【固定参考案例（均判误报，仅供参考）】
以下案例展示口语/叙述中文术语被代词/泛指/同义词替代的典型误报场景。

案例1：原文「大人，请听我一言。」→ 译文「Please, listen to me.」→ 误报。对话中尊称省略为祈使句开头。
案例2：原文「何老板已经为我们准备好了客房。」→ 译文「Our host has already prepared the guest rooms for us.」→ 误报。"our host"自然指代已知人物。
案例3：原文「既然少东家这么说了，那我也没意见。」→ 译文「Since he said so, I have no objections.」→ 误报。代词指代前文人物。
案例4：原文「虽然不羡仙很危险，但我必须去。」→ 译文「Although it's dangerous here, I must go.」→ 误报。"here"替代所在场所。
案例5：原文「我想念凉州的美酒。」→ 译文「I miss the wine there.」→ 误报。"there"指代已提及地点。
案例6：原文「如果真气不顺，强行修炼只会适得其反。」→ 译文「If vital energy isn't flowing correctly, forcing cultivation will only backfire.」→ 误报。同义替换。
案例7：原文「连夜奔波大家都累了，今晚我们就在前面镇上的客栈歇脚吧。」→ 译文「Everyone is tired from riding all night. Let's rest at the tavern up ahead.」→ 误报。同义替换。
案例8：原文「幸亏那位路过的游侠昨夜替我们解了围。」→ 译文「Fortunately, that passing wandering swordsman helped us out last night.」→ 误报。描述性概括。

【复核步骤】
1. 逐条检查 A/B/C/D/E/F，能明确指出命中的具体条款 → 判误报
2. 无法明确命中任何一条 → 判真错误

先写判定理由，再给出标签。输出 JSON，不要其他文字：
{{"llm_analysis": "判定理由（不超过100字）", "final_label": "真错误" 或 "误报"}}"""


@dataclass
class ReviewResult:
    final_label:  str
    llm_analysis: str
    raw_response: str
    prompt_used:  str


def _parse(raw: str) -> dict:
    text = re.sub(r'```(?:json)?\s*', '', raw, flags=re.IGNORECASE).strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            d = json.loads(m.group())
            if "final_label" in d:
                return d
        except json.JSONDecodeError:
            pass
    lm = re.search(r'"final_label"\s*:\s*"([^"]*)"', text)
    rm = re.search(r'"llm_analysis"\s*:\s*"([^"]*)"', text)
    if lm and lm.group(1) in ("真错误", "误报"):
        return {"final_label": lm.group(1), "llm_analysis": rm.group(1) if rm else "（解析不完整）"}
    return {"final_label": "真错误", "llm_analysis": f"LLM响应解析失败，默认真错误：{raw[:100]}"}


async def llm_secondary_review(
    error_type: str,
    error_description: str,
    source_text: str,
    target_text: str,
    search_results: list[Any],
    severity: str = "Minor",
    note: str = "",
) -> ReviewResult:
    if not search_results:
        cases_block = "（无匹配的历史案例，请完全依据规则独立判断）"
    else:
        top = search_results[0]
        reason = top.reason or top.false_alarm_reason
        lines = [
            "--- 参考案例 ---",
            f"案例ID: {top.case_id}",
            f"相似度: {top.similarity:.3f}",
            f"人工标签: {top.review_label or '（无）'}",
            f"案例原文: {top.source_text or '（无）'}",
            f"案例译文: {top.target_text or '（无）'}",
        ]
        if reason:
            lines.append(f"判定依据: {reason}")
        cases_block = "\n".join(lines)

    if search_results and search_results[0].similarity < config.SIM_WARN_THRESHOLD:
        cases_block = f"（以下案例相似度较低（{search_results[0].similarity:.2f}），仅供参考）\n\n" + cases_block

    similar_cases_block = f"【历史相似案例】\n{cases_block}"

    note_block = f"\n【备注】\n{note}\n" if note and note.strip() else "\n"

    prompt = REVIEW_PROMPT.format(
        error_type=error_type,
        error_description=error_description,
        severity=severity,
        source_text=source_text or "（无）",
        target_text=target_text or "（无）",
        note_block=note_block,
        similar_cases_block=similar_cases_block,
    )

    _MAX_RETRIES = 5
    _RETRY_DELAY = 2
    raw = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = await _get_client().chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                timeout=90,
            )
            raw = resp.choices[0].message.content
            if raw and raw.strip():
                break
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY)
            else:
                return ReviewResult(final_label="真错误", llm_analysis="LLM返回空响应", raw_response="", prompt_used=prompt)
        except Exception as e:
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)
            else:
                return ReviewResult(final_label="真错误", llm_analysis=f"LLM调用失败：{e}", raw_response=str(e), prompt_used=prompt)

    parsed = _parse(raw)
    return ReviewResult(final_label=parsed["final_label"], llm_analysis=parsed["llm_analysis"], raw_response=raw, prompt_used=prompt)


def llm_secondary_review_sync(*args, **kwargs) -> "ReviewResult":
    """Sync wrapper for test scripts."""
    return asyncio.run(llm_secondary_review(*args, **kwargs))


def full_decision(
    error_type: str,
    error_description: str,
    source_text: str = "",
    target_text: str = "",
    top_k: int = 3,
) -> dict:
    from rag.search import search_similar, decide
    results  = search_similar(error_description=error_description, error_type=error_type, top_k=top_k)
    decision = decide(results)

    out = {
        "decision":       decision,
        "final_label":    None,
        "reason":         "",
        "top_similarity": results[0].similarity if results else 0.0,
        "top_case_id":    results[0].case_id if results else None,
        "search_results": results,
        "review_result":  None,
    }

    if decision == "direct_pass":
        out["final_label"] = "误报"
        out["reason"] = f"高置信度匹配历史误报案例 (case_id={results[0].case_id}, sim={results[0].similarity:.3f})"

    elif decision == "direct_confirm":
        out["final_label"] = "真错误"
        out["reason"] = f"案例库一致判真错误 (top-3 标签一致, top_sim={results[0].similarity:.3f})"

    elif decision == "llm_review":
        review = llm_secondary_review_sync(error_type, error_description, source_text, target_text, results)
        out["final_label"]   = review.final_label
        out["reason"]        = review.llm_analysis
        out["review_result"] = review

    else:
        out["reason"] = "无高置信度匹配，维持初检结论"

    return out
