"""Export the local knowledge bank as portable JSON / GraphML.

The bank already lives as an evidence graph in SQLite (documents → chunks →
claims → entities/relationships). This module dumps that store in formats you
can open elsewhere — Obsidian, Neo4j, Gephi, a laptop clone — without waiting
for roadmap AS-04 (one-tap product export).

Usage:
    python -m zengrowth.knowledge.export
    python -m zengrowth.knowledge.export --out exports/bank --format all
    python -m zengrowth.knowledge.export --format graphml
    python -m zengrowth.knowledge.export --format json --no-chunks
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ElementTree, SubElement

from sqlmodel import Session, select

from ..db import get_engine, init_db
from ..models import (
    ClaimDocumentLink,
    ClaimFacet,
    EntityDocumentLink,
    EvidenceClaim,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceChunk,
    SourceDocument,
)
from .local_graph import KnowledgeGraph, build_local_graph

EXPORT_FORMAT_VERSION = 1


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _row_dict(row: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    data = row.model_dump()
    if exclude:
        for key in exclude:
            data.pop(key, None)
    return data


def build_bank_dump(
    session: Session,
    *,
    include_chunks: bool = True,
    include_embeddings: bool = False,
) -> dict[str, Any]:
    """Full structured dump of the evidence bank (tables → JSON-friendly dict)."""
    sources = list(session.exec(select(SourceDocument)))
    claims = list(session.exec(select(EvidenceClaim)))
    entities = list(session.exec(select(KnowledgeEntity)))
    relationships = list(session.exec(select(KnowledgeRelationship)))
    claim_links = list(session.exec(select(ClaimDocumentLink)))
    entity_links = list(session.exec(select(EntityDocumentLink)))
    facets = list(session.exec(select(ClaimFacet)))

    chunks_out: list[dict[str, Any]] = []
    if include_chunks:
        for chunk in session.exec(select(SourceChunk)):
            exclude = set() if include_embeddings else {"embedding"}
            chunks_out.append(_row_dict(chunk, exclude=exclude))

    return {
        "format": "zengrowth.knowledge.bank",
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "counts": {
            "sources": len(sources),
            "chunks": len(chunks_out),
            "claims": len(claims),
            "entities": len(entities),
            "relationships": len(relationships),
            "claim_document_links": len(claim_links),
            "entity_document_links": len(entity_links),
            "claim_facets": len(facets),
        },
        "sources": [_row_dict(row) for row in sources],
        "chunks": chunks_out,
        "claims": [_row_dict(row) for row in claims],
        "entities": [_row_dict(row) for row in entities],
        "relationships": [_row_dict(row) for row in relationships],
        "claim_document_links": [_row_dict(row) for row in claim_links],
        "entity_document_links": [_row_dict(row) for row in entity_links],
        "claim_facets": [_row_dict(row) for row in facets],
    }


def build_graph_json(
    session: Session,
    *,
    include_claims: bool = True,
    include_entities: bool = True,
    include_lineage: bool = True,
) -> dict[str, Any]:
    """UI-shaped ``{nodes, edges}`` projection (same as ``GET /knowledge/graph``)."""
    graph = build_local_graph(
        session,
        include_claims=include_claims,
        include_entities=include_entities,
        include_lineage=include_lineage,
    )
    return {
        "format": "zengrowth.knowledge.graph",
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
    }


def build_entity_graphml(session: Session) -> Element:
    """True entity–relationship GraphML for Gephi / Neo4j / yEd import."""
    entities = [e for e in session.exec(select(KnowledgeEntity)) if e.id is not None]
    relationships = list(session.exec(select(KnowledgeRelationship)))
    entity_ids = {e.id for e in entities}

    root = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for key_id, attr_name, for_what, attr_type in (
        ("d_label", "label", "node", "string"),
        ("d_kind", "kind", "node", "string"),
        ("d_entity_type", "entity_type", "node", "string"),
        ("d_normalized", "normalized_name", "node", "string"),
        ("d_rel_type", "relationship_type", "edge", "string"),
        ("d_confidence", "confidence", "edge", "double"),
        ("d_claim", "source_claim_id", "edge", "string"),
    ):
        SubElement(
            root,
            "key",
            id=key_id,
            **{"for": for_what, "attr.name": attr_name, "attr.type": attr_type},
        )

    graph_el = SubElement(root, "graph", id="knowledge", edgedefault="directed")
    for entity in entities:
        assert entity.id is not None
        node = SubElement(graph_el, "node", id=f"entity:{entity.id}")
        SubElement(node, "data", key="d_label").text = entity.name
        SubElement(node, "data", key="d_kind").text = "entity"
        SubElement(node, "data", key="d_entity_type").text = entity.entity_type
        SubElement(node, "data", key="d_normalized").text = entity.normalized_name

    for rel in relationships:
        if (
            rel.id is None
            or rel.source_entity_id not in entity_ids
            or rel.target_entity_id not in entity_ids
        ):
            continue
        edge = SubElement(
            graph_el,
            "edge",
            id=f"rel:{rel.id}",
            source=f"entity:{rel.source_entity_id}",
            target=f"entity:{rel.target_entity_id}",
        )
        SubElement(edge, "data", key="d_rel_type").text = rel.relationship_type
        SubElement(edge, "data", key="d_confidence").text = str(rel.confidence)
        if rel.source_claim_id:
            SubElement(edge, "data", key="d_claim").text = rel.source_claim_id

    return root


def build_projection_graphml(graph: KnowledgeGraph) -> Element:
    """GraphML for the UI projection (sources / claims / entities / materials)."""
    root = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for key_id, attr_name, for_what, attr_type in (
        ("d_label", "label", "node", "string"),
        ("d_kind", "kind", "node", "string"),
        ("d_detail", "detail", "node", "string"),
        ("d_group", "group", "node", "string"),
        ("d_edge_kind", "kind", "edge", "string"),
    ):
        SubElement(
            root,
            "key",
            id=key_id,
            **{"for": for_what, "attr.name": attr_name, "attr.type": attr_type},
        )

    graph_el = SubElement(root, "graph", id="projection", edgedefault="directed")
    for node in graph.nodes:
        el = SubElement(graph_el, "node", id=node.id)
        SubElement(el, "data", key="d_label").text = node.label
        SubElement(el, "data", key="d_kind").text = node.kind
        if node.detail:
            SubElement(el, "data", key="d_detail").text = node.detail
        if node.group:
            SubElement(el, "data", key="d_group").text = node.group

    for edge in graph.edges:
        el = SubElement(
            graph_el,
            "edge",
            id=edge.id,
            source=edge.source,
            target=edge.target,
        )
        SubElement(el, "data", key="d_edge_kind").text = edge.kind

    return root


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_graphml(path: Path, root: Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def export_knowledge_bank(
    session: Session,
    out_dir: Path,
    *,
    formats: set[str],
    include_chunks: bool = True,
    include_embeddings: bool = False,
) -> dict[str, Any]:
    """Write selected export artifacts under ``out_dir``; return the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    counts: dict[str, int] = {}

    if "json" in formats or "all" in formats:
        bank = build_bank_dump(
            session,
            include_chunks=include_chunks,
            include_embeddings=include_embeddings,
        )
        _write_json(out_dir / "bank.json", bank)
        written.append("bank.json")
        counts = dict(bank["counts"])

        graph_payload = build_graph_json(session)
        _write_json(out_dir / "graph.json", graph_payload)
        written.append("graph.json")
        counts["graph_nodes"] = len(graph_payload["nodes"])
        counts["graph_edges"] = len(graph_payload["edges"])

    if "graphml" in formats or "all" in formats:
        _write_graphml(out_dir / "entity_graph.graphml", build_entity_graphml(session))
        written.append("entity_graph.graphml")

        projection = build_local_graph(
            session,
            include_claims=True,
            include_entities=True,
            include_lineage=True,
        )
        _write_graphml(out_dir / "projection.graphml", build_projection_graphml(projection))
        written.append("projection.graphml")
        if "graph_nodes" not in counts:
            counts["graph_nodes"] = len(projection.nodes)
            counts["graph_edges"] = len(projection.edges)

    manifest = {
        "format": "zengrowth.knowledge.export",
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "out_dir": str(out_dir),
        "files": [*written, "manifest.json"],
        "counts": counts,
        "notes": [
            "bank.json is the full evidence tables dump (portable re-import source).",
            "graph.json matches GET /knowledge/graph (UI projection).",
            "entity_graph.graphml is typed entity→entity edges (WORKED_ON, USED, …).",
            "projection.graphml is the same multi-kind graph the UI renders.",
            "File originals live under data/knowledge/; pair with deploy/sync-bank-to-local.sh.",
        ],
    }
    _write_json(out_dir / "manifest.json", manifest)
    return manifest


def _default_out_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("exports") / f"knowledge-{stamp}"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the ZenGrowth knowledge bank as JSON and/or GraphML.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: exports/knowledge-<UTC timestamp>)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "graphml", "all"),
        default="all",
        help="Which artifacts to write (default: all)",
    )
    parser.add_argument(
        "--no-chunks",
        action="store_true",
        help="Omit source chunks from bank.json (smaller dump)",
    )
    parser.add_argument(
        "--include-embeddings",
        action="store_true",
        help="Include chunk embedding vectors in bank.json (large)",
    )
    return parser.parse_args(argv)


def _main(argv: list[str]) -> int:
    args = _parse_args(argv)
    out_dir = args.out or _default_out_dir()
    init_db()
    with Session(get_engine()) as session:
        manifest = export_knowledge_bank(
            session,
            out_dir,
            formats={args.format},
            include_chunks=not args.no_chunks,
            include_embeddings=args.include_embeddings,
        )
    print(f"Exported knowledge bank → {out_dir}")
    for name in manifest["files"]:
        print(f"  - {name}")
    counts = manifest.get("counts") or {}
    if counts:
        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        print(f"  counts: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
