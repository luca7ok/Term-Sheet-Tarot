import argparse

from tarot.synthetic.term_sheets import write_corpus

p = argparse.ArgumentParser(prog="python -m tarot.synthetic")
p.add_argument("--n", type=int, default=50)
p.add_argument("--seed", type=int, default=0)
p.add_argument("--out", default="data/synthetic/term_sheets")
a = p.parse_args()
print(f"wrote {write_corpus(a.n, a.seed, a.out)} documents to {a.out}")
