"""
Vault Graphify - Convert vault markdown notes into a knowledge graph.

Extracts entities, relationships, and concepts from markdown vault notes
to build a knowledge graph that can be queried for semantic understanding.

Useful for:
- Building character knowledge bases
- Extracting relationships between concepts
- Creating semantic indices for memory retrieval
- Visualizing character knowledge
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Represents a concept or entity in the knowledge graph."""
    name: str
    type: str  # 'concept', 'person', 'place', 'event', 'object'
    definition: str
    mentions: int = 1
    source_file: str = ""
    
    def to_dict(self):
        return asdict(self)


@dataclass
class Relationship:
    """Represents a relationship between entities."""
    source: str
    relation: str
    target: str
    context: str = ""
    strength: float = 1.0
    
    def to_dict(self):
        return asdict(self)


class VaultGraphifier:
    """Converts vault markdown into a knowledge graph."""
    
    # Patterns for entity extraction
    HEADING_PATTERN = re.compile(r'^#{1,6}\s+(.+)$', re.MULTILINE)
    LINK_PATTERN = re.compile(r'\[\[(.+?)\]\]|\[([^\]]+)\]\(([^\)]+)\)')
    BOLD_PATTERN = re.compile(r'\*\*(.+?)\*\*')
    
    # Common relationship markers
    RELATIONSHIP_MARKERS = {
        'related to': 'related_to',
        'is a': 'is_a',
        'has': 'has',
        'part of': 'part_of',
        'caused by': 'caused_by',
        'connected to': 'connected_to',
        'derived from': 'derived_from',
        'opposite of': 'opposite_of',
    }
    
    def __init__(self):
        """Initialize the graphifier."""
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.files_processed = 0
    
    def process_vault(self, vault_dir: Path) -> Dict:
        """Process all markdown files in vault directory.
        
        Args:
            vault_dir: Path to vault directory
            
        Returns:
            Dict with graph data (entities and relationships)
        """
        vault_dir = Path(vault_dir)
        if not vault_dir.is_dir():
            logger.error(f"Vault directory not found: {vault_dir}")
            return {"entities": {}, "relationships": [], "stats": {}}
        
        # Process all markdown files
        for md_file in vault_dir.glob('**/*.md'):
            self._process_file(md_file, vault_dir)
        
        return self.to_dict()
    
    def _process_file(self, file_path: Path, vault_dir: Path):
        """Process a single markdown file.
        
        Args:
            file_path: Path to markdown file
            vault_dir: Root vault directory
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            relative_path = file_path.relative_to(vault_dir)
            
            # Extract headings as entities
            for match in self.HEADING_PATTERN.finditer(content):
                heading = match.group(1).strip()
                self._add_entity(heading, 'concept', heading, str(relative_path))
            
            # Extract bold text as potential entities
            for match in self.BOLD_PATTERN.finditer(content):
                text = match.group(1).strip()
                if 2 < len(text) < 100:  # Reasonable length
                    self._add_entity(text, 'concept', text, str(relative_path))
            
            # Extract wikilinks
            for match in self.LINK_PATTERN.finditer(content):
                if match.group(1):  # Wikilink format
                    linked = match.group(1).strip()
                    self._add_entity(linked, 'concept', linked, str(relative_path))
            
            # Extract relationships from text
            self._extract_relationships(content)
            
            self.files_processed += 1
            logger.info(f"Processed vault file: {relative_path}")
        
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
    
    def _add_entity(
        self,
        name: str,
        entity_type: str,
        definition: str,
        source_file: str
    ):
        """Add or update an entity in the graph.
        
        Args:
            name: Entity name
            entity_type: Type of entity
            definition: Entity definition
            source_file: Source file path
        """
        name_lower = name.lower().strip()
        
        if name_lower in self.entities:
            # Update mention count
            self.entities[name_lower].mentions += 1
        else:
            # Add new entity
            self.entities[name_lower] = Entity(
                name=name,
                type=entity_type,
                definition=definition,
                source_file=source_file
            )
    
    def _extract_relationships(self, content: str):
        """Extract relationships from text content.
        
        Args:
            content: Markdown content to analyze
        """
        # Simple relationship extraction based on markers
        for marker, relation_type in self.RELATIONSHIP_MARKERS.items():
            pattern = re.compile(
                rf'(\w+[\w\s]*?)\s+{re.escape(marker)}\s+([\w]+[\w\s]*?)[\.\,\n]',
                re.IGNORECASE
            )
            
            for match in pattern.finditer(content):
                source = match.group(1).strip().lower()
                target = match.group(2).strip().lower()
                
                if source and target and source != target:
                    self.relationships.append(Relationship(
                        source=source,
                        relation=relation_type,
                        target=target,
                        context=match.group(0)[:100],
                        strength=1.0
                    ))
    
    def to_dict(self) -> Dict:
        """Convert graph to dictionary format.
        
        Returns:
            Dict with entities, relationships, and stats
        """
        return {
            "entities": {
                name: entity.to_dict()
                for name, entity in self.entities.items()
            },
            "relationships": [rel.to_dict() for rel in self.relationships],
            "stats": {
                "total_entities": len(self.entities),
                "total_relationships": len(self.relationships),
                "files_processed": self.files_processed,
                "entity_types": self._count_entity_types(),
                "relationship_types": self._count_relationship_types(),
            }
        }
    
    def _count_entity_types(self) -> Dict[str, int]:
        """Count entities by type.
        
        Returns:
            Dict of type -> count
        """
        counts = defaultdict(int)
        for entity in self.entities.values():
            counts[entity.type] += 1
        return dict(counts)
    
    def _count_relationship_types(self) -> Dict[str, int]:
        """Count relationships by type.
        
        Returns:
            Dict of type -> count
        """
        counts = defaultdict(int)
        for rel in self.relationships:
            counts[rel.relation] += 1
        return dict(counts)
    
    def save_graph(self, output_path: Path):
        """Save knowledge graph to JSON file.
        
        Args:
            output_path: Path to save JSON to
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        
        logger.info(f"Knowledge graph saved to {output_path}")
    
    def get_entity_summary(self, max_entities: int = 10) -> str:
        """Get a text summary of top entities.
        
        Args:
            max_entities: Maximum entities to include
            
        Returns:
            Text summary
        """
        # Sort by mention count
        top = sorted(
            self.entities.values(),
            key=lambda e: e.mentions,
            reverse=True
        )[:max_entities]
        
        lines = ["## Knowledge Graph Summary\n"]
        for entity in top:
            lines.append(f"- **{entity.name}** ({entity.mentions} mentions)")
        
        return '\n'.join(lines)


def graphify_vault_periodic(vault_dir: Path, output_dir: Path, every_n_turns: int = 50):
    """Generate knowledge graph periodically during a session.
    
    Useful for building up character knowledge over time.
    
    Args:
        vault_dir: Vault directory to process
        output_dir: Output directory for graphs
        every_n_turns: Generate graph every N conversation turns
    """
    graphifier = VaultGraphifier()
    graph = graphifier.process_vault(vault_dir)
    
    # Save with timestamp
    from datetime import datetime
    timestamp = datetime.now().isoformat().split('.')[0].replace(':', '-')
    output_file = output_dir / f"knowledge_graph_{timestamp}.json"
    
    graphifier.save_graph(output_file)
    return graph
