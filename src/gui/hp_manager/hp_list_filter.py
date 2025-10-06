from typing import Dict, List, Set


class HPListFilter:
    def __init__(self, expanded_hp_ids: Set[str]):
        self.expanded_hp_ids = expanded_hp_ids

    def get_sorted_hp_list(
        self, hp_list_data: List[Dict], hp_state_filter: List[str]
    ) -> List[Dict]:
        filtered_data = [
            hp for hp in hp_list_data if hp.get("state", "") in hp_state_filter
        ]
        parents = self._get_parents(filtered_data)
        multihop_children = self._get_multihop_children(filtered_data)
        regular_children = self._get_regular_children(filtered_data)
        return self._build_sorted_hierarchy(
            parents, multihop_children, regular_children
        )

    def _get_parents(self, filtered_data: List[Dict]) -> List[Dict]:
        return [
            hp
            for hp in filtered_data
            if not hp.get("is_child", False) and hp.get("side", "") == "PARENT"
        ]

    def _get_multihop_children(self, filtered_data: List[Dict]) -> List[Dict]:
        return [
            hp
            for hp in filtered_data
            if hp.get("is_child", False)
            and hp.get("hp_id", "")[-1:].isalpha()
            and "_" not in hp.get("hp_id", "")
        ]

    def _get_regular_children(self, filtered_data: List[Dict]) -> List[Dict]:
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
        sorted_list = []
        for parent in sorted(parents, key=lambda x: int(x.get("hp_id", "0"))):
            parent_id = parent["hp_id"]
            parent_multihop_children = self._find_parent_multihop_children(
                parent_id, multihop_children
            )
            parent_regular_children = self._find_parent_regular_children(
                parent_id, regular_children
            )
            all_children = parent_multihop_children + parent_regular_children

            parent["has_children"] = True
            parent["is_expanded"] = parent_id in self.expanded_hp_ids
            sorted_list.append(parent)

            if parent_id in self.expanded_hp_ids:
                sorted_list.extend(self._sort_children(all_children))

        return sorted_list

    def _find_parent_multihop_children(
        self, parent_id: str, multihop_children: List[Dict]
    ) -> List[Dict]:
        return [
            c
            for c in multihop_children
            if c.get("parent_hp_id") == parent_id
            or c.get("hp_id", "")[:-1] == parent_id
        ]

    def _find_parent_regular_children(
        self, parent_id: str, regular_children: List[Dict]
    ) -> List[Dict]:
        return [
            c
            for c in regular_children
            if c.get("parent_hp_id") == parent_id
            or c.get("hp_id", "").startswith(f"{parent_id}_")
        ]

    def _sort_children(self, children: List[Dict]) -> List[Dict]:
        return sorted(children, key=lambda x: (x.get("hp_id", ""), x.get("side", "")))

    @staticmethod
    def get_filter_preset(filter_name: str) -> List[str]:
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
