from duckduckgo_search import DDGS

ddgs = DDGS()
results = ddgs.text("site:boards.greenhouse.io stripe", max_results=3)
for r in results:
    print(r['href'])

results = ddgs.text("site:jobs.lever.co netflix", max_results=3)
for r in results:
    print(r['href'])
