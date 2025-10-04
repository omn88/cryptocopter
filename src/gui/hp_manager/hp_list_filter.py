"""
HP List Filter Module

This module handles filtering and sorting of HP positions for display.

Single Responsibility: List filtering and sorting logic
"""

from typing import Dict, List, Set


class HPListFilter:
    """
    Responsible for filtering and sorting HP position lists.

    Handles:
    - State-based filtering
    - Parent/child hierarchy sorting
    - Expansion state management
    """

    def __init__(self, expanded_hp_ids: Set[str]):
        """
        Initialize filter with expansion state.

        Args:
            expanded_hp_ids: Set of expanded parent HP IDs
        """
        self.expanded_hp_ids = expanded_hp_ids

    def get_sorted_hp_list(
        self, hp_list_data: List[Dict], hp_state_filter: List[str]
    ) -> List[Dict]:
        """
        Get sorted and filtered HP list with parent-child hierarchy.

        Args:
            hp_list_data: Full list of HP position data
            hp_state_filter: List of states to include in filter

        Returns:
            Sorted list with parents followed by their expanded children
        """
        # Filter by state
        filtered_data = [
            hp for hp in hp_list_data if hp.get("state", "") in hp_state_filter
        ]

        # Categorize positions
        parents = self._get_parents(filtered_data)
        multihop_children = self._get_multihop_children(filtered_data)
        regular_children = self._get_regular_children(filtered_data)

        # Build sorted list with hierarchy
        return self._build_sorted_hierarchy(
            parents, multihop_children, regular_children
        )

    def _get_parents(self, filtered_data: List[Dict]) -> List[Dict]:
        """Extract parent positions from filtered data."""
        return [
            hp
            for hp in filtered_data
            if not hp.get("is_child", False) and hp.get("side", "") == "PARENT"
        ]

    def _get_multihop_children(self, filtered_data: List[Dict]) -> List[Dict]:
        """Extract multihop children (1000a, 1000b) from filtered data."""
        return [
            hp
            for hp in filtered_data
            if hp.get("is_child", False)
            and hp.get("hp_id", "")[-1:].isalpha()
            and "_" not in hp.get("hp_id", "")
        ]

    def _get_regular_children(self, filtered_data: List[Dict]) -> List[Dict]:
        """Extract regular children (1000_BUY, 1000_SELL) from filtered data."""
        return [
            hp
            for hp in filtered_data
            if hp.get("is_child", False) and "_" in hp.get("hp_id", "")
        ]

    def _build_sorted_hierarchy(
        self,
        parents: List[Dict],
        multihop_children: List[Dict],
        regular_children: List[Dict],
    ) -> List[Dict]:
        """
        Build sorted hierarchy with parents and their children.

        Args:
            parents: List of parent positions
            multihop_children: List of multihop child positions
            regular_children: List of regular child positions

        Returns:
            Sorted list with parents followed by expanded children
        """
        sorted_list = []

        for parent in sorted(parents, key=lambda x: int(x.get("hp_id", "0"))):
            parent_id = parent["hp_id"]

            # Find children for this parent
            parent_multihop_children = self._find_parent_multihop_children(
                parent_id, multihop_children
            )
            parent_regular_children = self._find_parent_regular_children(
                parent_id, regular_children
            )
            all_children = parent_multihop_children + parent_regular_children

            # Set parent expansion state
            parent["has_children"] = True
            parent["is_expanded"] = parent_id in self.expanded_hp_ids
            sorted_list.append(parent)

            # Add children if parent is expanded
            if parent_id in self.expanded_hp_ids:
                sorted_children = self._sort_children(all_children)
                sorted_list.extend(sorted_children)

        return sorted_list

    def _find_parent_multihop_children(
        self, parent_id: str, multihop_children: List[Dict]
    ) -> List[Dict]:
        """Find multihop children belonging to a specific parent."""
        return [
            c
            for c in multihop_children
            if c.get("parent_hp_id") == parent_id
            or c.get("hp_id", "")[:-1] == parent_id
        ]

    def _find_parent_regular_children(
        self, parent_id: str, regular_children: List[Dict]
    ) -> List[Dict]:
        """Find regular children belonging to a specific parent."""
        return [
            c
            for c in regular_children
            if c.get("parent_hp_id") == parent_id
            or c.get("hp_id", "").startswith(f"{parent_id}_")
        ]

    def _sort_children(self, children: List[Dict]) -> List[Dict]:
        """Sort children by HP ID and side."""
        return sorted(children, key=lambda x: (x.get("hp_id", ""), x.get("side", "")))

    @staticmethod
    def get_filter_preset(filter_name: str) -> List[str]:
        """
        Get predefined filter preset by name.

        Args:
            filter_name: Name of the filter preset

        Returns:
            List of state strings to include in filter
        """
        presets = {
            "Active States (11)": [
                "NEW",
                "BUYING",
                "PARTIALLY_BOUGHT",
                "BOUGHT",
                "READY_TO_SELL",
                "SELLING",
                "PARTIALLY_SOLD",
                "SOLD_PART_BOUGHT",
                "WAITING_CHILD",
                "NONE",
            ],
            "All States (13)": [
                "NEW",
                "BUYING",
                "PARTIALLY_BOUGHT",
                "BOUGHT",
                "READY_TO_SELL",
                "SELLING",
                "PARTIALLY_SOLD",
                "SOLD",
                "PART_SOLD_PART_BOUGHT",
                "SOLD_PART_BOUGHT",
                "CLOSED",
                "WAITING_CHILD",
                "NONE",
            ],
            "Show Only CLOSED": ["CLOSED"],
            "Show Only SOLD": ["SOLD"],
        }

        return presets.get(filter_name, presets["Active States (11)"])
