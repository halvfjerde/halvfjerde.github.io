"""같은 출발지에서 발차 시각이 겹치는 행선지 묶음 (coincide.py·routes2.py 가 같이 쓴다).
묶음: 행선지마다 그 시각을 모두 담는 가장 작은 큰 행선지를 부모로 (큰 쪽이 너무 촘촘하면 우연으로 보고 잇지 않는다)."""
import collections

def trees(blocks):
    """blocks: 행선지 → (발차 시각 집합, 소요). 돌려줌: [(뿌리, [딸린 행선지…])]"""
    par = {}
    for x, (s, du) in blocks.items():
        sup = [y for y, (s2, du2) in blocks.items() if y != x and s <= s2 and (len(s) < len(s2) or du2 > du or (du2 == du and y > x))]
        if not sup: continue
        y = min(sup, key=lambda y: (len(blocks[y][0]), -blocks[y][1]))
        if len(blocks[y][0]) > 3 * len(s) and len(blocks[y][0]) > len(s) + 5: continue
        par[x] = y
    roots = collections.defaultdict(list)
    for x in par:
        r = x
        while r in par: r = par[r]
        roots[r].append(x)
    return list(roots.items())

def sure(blocks, xs):
    """같은 차로 볼 만한가: 가장 적은 행선지도 15편 넘거나, 행선지 넷 넘게 편수가 같다 (사람이 확인한 기준)"""
    ns = [len(blocks[x][0]) for x in xs]
    return min(ns) >= 15 or (len(xs) >= 4 and len(set(ns)) == 1)

def ordered(blocks, xs):
    """소요가 모두 달라 들르는 차례가 시각으로 정해지는가 (같으면 사람이 차례를 본다)"""
    ds = [blocks[x][1] for x in xs]
    return len(set(ds)) == len(ds)
