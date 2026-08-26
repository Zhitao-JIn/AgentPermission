from ..approval import ApprovalRequest


class InMemoryApprovalStore:
    """把审批请求放在进程内存里，**不落盘**。

    审批请求的生命周期是 request → approve / reject / expire，秒级，而且决策在
    `check_permission()` 的同一个作用域里当场做完 —— 它没有任何理由活过进程。
    落盘只会留下一份永远不清理、永远没人读的历史，还得为此处理原子写和并发覆盖
    两个本来不存在的问题。

    真要做异步审批（进程 A 发起、人在别处批、A 轮询），那时需要的是一个能跨进程的
    存储，而不是把文件写回来 —— 那是另一件事，届时新写一个实现即可，
    `ApprovalStore` 这个 Protocol 就是为此留的。

    key 是 `approval_id`（uuid4，全局唯一），所以**全进程一个实例就够**，
    不按 permission 或别的什么分库 —— 见 `agent_permission.approval_store`。
    """

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def create(self, request: ApprovalRequest) -> None:
        assert request.approval_id not in self._requests, (
            f"approval {request.approval_id} already exists"
        )
        self.save(request)

    def save(self, request: ApprovalRequest) -> None:
        self._requests[request.approval_id] = request
