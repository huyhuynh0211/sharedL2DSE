import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--binary", type=str, required=True)
parser.add_argument("--l2_size", type=str, default="1MB")
parser.add_argument("--l2_assoc", type=int, default=16)
parser.add_argument("--footprint", type=int, default=2097152)
parser.add_argument("--stride", type=int, default=64)

args = parser.parse_args()

print("binary    =", args.binary)
print("l2_size   =", args.l2_size)
print("l2_assoc  =", args.l2_assoc)
print("footprint =", args.footprint)
print("stride    =", args.stride)

