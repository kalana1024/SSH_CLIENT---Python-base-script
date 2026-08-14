"""Hexdump utility for debugging binary SSH output."""


def hexdump(src: bytes, length: int = 16) -> str:
    result = []
    for i in range(0, len(src), length):
        s = src[i:i + length]
        hexa = ' '.join(f"{x:02X}" for x in s)
        text = ''.join(chr(x) if 0x20 <= x < 0x7F else '.' for x in s)
        result.append(f"{i:04X}   {hexa:<{length * 3}}   {text}")
    return '\n'.join(result)
