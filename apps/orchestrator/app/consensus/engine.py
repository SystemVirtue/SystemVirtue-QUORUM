import difflib
import re
from app.core.schemas import ConsensusReport, MemberOutput


def extract_code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, flags=re.S)


def normalise_code(code: str) -> str:
    code = re.sub(r"#.*", "", code)
    code = re.sub(r"//.*", "", code)
    code = re.sub(r"\s+", " ", code).strip()
    names: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in {"def", "class", "return", "const", "let", "var", "function", "fn", "func", "SELECT", "FROM"}:
            return name
        if name not in names:
            names[name] = f"v{len(names) + 1}"
        return names[name]

    return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", repl, code)


def extract_claims(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    triggers = ("should", "must", "use", "avoid", "the bug is", "change to")
    return [s.strip() for s in sentences if any(t in s.lower() for t in triggers) or re.match(r"^(Add|Remove|Change|Use|Avoid)\b", s)]


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def consensus(prompt: str, revised_completions: list[MemberOutput], mode: str) -> ConsensusReport:
    if not revised_completions:
        return ConsensusReport(consensus_items=[], disagreements=[], candidate_ranking=[], overall_consensus_score=0)

    texts = [c.revised_text or c.output_text for c in revised_completions]
    pair_scores: list[float] = []
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            pair_scores.append(similarity(a, b))
    overall = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0

    consensus_items: list[dict] = []
    disagreements: list[dict] = []
    all_claims = [(c.label, claim) for c in revised_completions for claim in extract_claims(c.revised_text or c.output_text)]
    for label, claim in all_claims[:12]:
        matches = [other_label for other_label, other in all_claims if similarity(claim.lower(), other.lower()) >= 0.78]
        item = {"claim": claim, "supporters": sorted(set(matches))}
        if len(set(matches)) >= max(2, len(revised_completions) // 2):
            consensus_items.append(item)
        else:
            disagreements.append({"topic": claim[:80], "positions": [{"label": label, "claim": claim}]})

    rankings = []
    for c in revised_completions:
        text = c.revised_text or c.output_text
        peer_similarity = sum(similarity(text, t) for t in texts) / len(texts)
        format_quality = 1.0 if len(text.strip()) > 80 else 0.4
        critique_acceptance = 0.7
        score = (
            0.45 * peer_similarity
            + 0.25 * (c.confidence / 100)
            + 0.15 * format_quality
            + 0.10 * critique_acceptance
            + 0.05 * 0.8
        )
        rankings.append({"label": c.label, "model_id": c.model_id, "score": round(score, 4), "text": text})
    rankings.sort(key=lambda row: row["score"], reverse=True)
    return ConsensusReport(
        consensus_items=consensus_items,
        disagreements=disagreements,
        candidate_ranking=rankings,
        overall_consensus_score=round(overall, 4),
    )


def produce_diffs(winner: str, runners_up: list[str]) -> str:
    chunks = []
    for idx, runner in enumerate(runners_up, start=1):
        diff = difflib.unified_diff(
            runner.splitlines(), winner.splitlines(),
            fromfile=f"runner_{idx}", tofile="winner", lineterm="",
        )
        chunks.append("\n".join(diff))
    return "\n\n".join(chunks)
