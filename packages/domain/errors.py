class DomainError(Exception):
    """Base class for domain failures."""


class InvalidConditionRaw(DomainError):
    pass


class UnsupportedMarket(DomainError):
    pass


class SettlementError(DomainError):
    pass


class SettlementInputError(SettlementError):
    pass


class DuplicateBetError(DomainError):
    pass


class AlreadySettledError(DomainError):
    pass


class InsufficientBankrollError(DomainError):
    pass


class UnresolvedTeamError(DomainError):
    pass
