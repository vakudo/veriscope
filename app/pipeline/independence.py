import re

from app.pipeline.similarity import UnionFind, cosine
from app.schemas import EvidenceSource, SourceType

OPINION_PATTERN = re.compile(
    r"/(opinion|opinions|blog|blogs|column|columns|editorial|editorials|mnenie|mneniya)/",
    re.IGNORECASE,
)


async def mark_independence(
    llm,
    sources: list[EvidenceSource],
    threshold: float,
) -> list[EvidenceSource]:
    if not sources:
        return sources
    vectors = await llm.embed([f"{s.title}\n{s.snippet}" for s in sources])
    uf = UnionFind(len(sources))
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            if sources[i].domain and sources[i].domain == sources[j].domain:
                uf.union(i, j)
            elif cosine(vectors[i], vectors[j]) >= threshold:
                uf.union(i, j)
    root_to_cluster: dict[int, int] = {}
    for index, source in enumerate(sources):
        root = uf.find(index)
        source.cluster_id = root_to_cluster.setdefault(root, len(root_to_cluster))
    clusters: dict[int, list[EvidenceSource]] = {}
    for source in sources:
        clusters.setdefault(source.cluster_id, []).append(source)
    for members in clusters.values():
        dated = [s for s in members if s.published_at]
        earliest = min(dated, key=lambda s: s.published_at) if dated else None
        for source in members:
            if OPINION_PATTERN.search(source.url):
                source.source_type = SourceType.opinion
            elif len(members) == 1:
                source.source_type = SourceType.unknown
            elif source is earliest:
                source.source_type = SourceType.possible_primary
            else:
                source.source_type = SourceType.reprint
    return sources
