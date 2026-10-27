"""Bounded, lossless presentations of observed actions."""


def bounded(actions, buckets, limit, namespace="model_bucket"):
    """Build ordered range buckets without changing the underlying actions or their IDs.

    The returned aliases are registered in buckets and can be navigated with Session.expand.
    Reserve two slots in every child list for the session's back and root controls.
    """
    items = list(actions)
    level = 0
    while len(items) > limit:
        groups = []
        for start in range(0, len(items), limit - 2):
            children = items[start:start + limit - 2]
            ref = f"{namespace}_{limit}_{level}_{start // (limit - 2) + 1}"
            buckets[ref] = children
            count = sum(a.get("count", 1) if a.get("kind") == "expand" else 1 for a in children)
            groups.append({"id": ref, "kind": "expand", "bucket": ref,
                           "label": f"Actions {start + 1}–{start + len(children)}: "
                                    f"{children[0].get('label', '')[:45]} … {children[-1].get('label', '')[:45]}",
                           "count": count})
        items = groups
        level += 1
    return items
