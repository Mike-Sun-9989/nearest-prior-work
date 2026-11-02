import json
import re
import httpx

def fake_model(calls):
    """An OpenAI-style endpoint that marks a section at every H paragraph, labelled from its heading."""
    from nearest_prior_work.sections import classify_heading
    names = {"method": "methods", "skip": "references"}

    def handler(request):
        body = json.loads(request.content)
        calls.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        user = body["messages"][-1]["content"]
        if "connection test" in body["messages"][0]["content"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        secs, title = [{"start": 0, "heading": None, "label": "front_matter", "level": 1}], None
        for line in user.splitlines():
            if re.match(r"^\[(\d+)\] P Abstract", line):
                secs.append({"start": int(line[1:line.index("]")]), "heading": None, "label": "abstract", "level": 1})
            m = re.match(r"^\[(\d+)\] H (.*)$", line)
            if not m:
                continue
            i, head = int(m.group(1)), m.group(2)
            c = classify_heading(head)
            if c is None and title is None:
                title = i
                continue
            lab = names.get(c, c or "other")
            if i == 0:
                secs[0] = {"start": 0, "heading": head, "label": lab, "level": 1}
            else:
                secs.append({"start": i, "heading": head, "label": lab, "level": 1})
        js = {"paper_type": "quantitative_empirical", "title_par": title, "sections": secs, "notes": ""}
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(js) + "\n```"}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    return httpx.MockTransport(handler)

