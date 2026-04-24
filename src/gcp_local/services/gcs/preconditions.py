from dataclasses import dataclass

from gcp_local.services.gcs.models import ObjectRecord


class PreconditionFailed(Exception):
    pass


@dataclass
class Preconditions:
    if_generation_match: int | None = None
    if_generation_not_match: int | None = None
    if_metageneration_match: int | None = None
    if_metageneration_not_match: int | None = None


def evaluate_preconditions(pre: Preconditions, *, current: ObjectRecord | None) -> None:
    """Raise PreconditionFailed if any of the supplied preconditions fails."""

    if pre.if_generation_match is not None:
        if pre.if_generation_match == 0:
            if current is not None:
                raise PreconditionFailed("ifGenerationMatch=0 requires the object to not exist")
        else:
            if current is None or current.generation != pre.if_generation_match:
                raise PreconditionFailed(
                    f"ifGenerationMatch={pre.if_generation_match} does not match"
                )

    if (
        pre.if_generation_not_match is not None
        and current is not None
        and current.generation == pre.if_generation_not_match
    ):
        raise PreconditionFailed(f"ifGenerationNotMatch={pre.if_generation_not_match} matched")

    if pre.if_metageneration_match is not None and (
        current is None or current.metageneration != pre.if_metageneration_match
    ):
        raise PreconditionFailed(
            f"ifMetagenerationMatch={pre.if_metageneration_match} does not match"
        )

    if (
        pre.if_metageneration_not_match is not None
        and current is not None
        and current.metageneration == pre.if_metageneration_not_match
    ):
        raise PreconditionFailed(
            f"ifMetagenerationNotMatch={pre.if_metageneration_not_match} matched"
        )
