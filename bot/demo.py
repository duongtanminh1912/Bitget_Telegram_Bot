"""Offline smoke demo: python -m bot.demo. Uses no Telegram or network."""
from .core import Engine

def main():
    now=1793667600.0
    e=Engine(':memory:',lambda:now)
    e.tick(100,now)
    e.set_budget(50)
    key,sig=e.propose('long',100,99,102)
    print('PAPER signal:',sig)
    print('PAPER position:',e.approve(key,100,now))
    e.tick(102,now)
    print('After TP:', e.snapshot())
    e.db.close()

if __name__=='__main__': main()
