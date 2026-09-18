# from deepgram import DeepgramClient, PrerecordedOptions

# dg = DeepgramClient("75ace6c29feeb1ce6a4cd63e91f218845a832de6")
# opts = PrerecordedOptions(model="nova-2", diarize=True,
#                           punctuate=True, utterances=True)
# with open("/Users/pranav/Code/CIMET/Sadar.m4a", "rb") as f:
#     res = dg.listen.prerecorded.v("1").transcribe_file({"buffer": f}, opts)

# print(res.to_json(indent=2)[:3000])





import requests, json

API_KEY = "75ace6c29feeb1ce6a4cd63e91f218845a832de6"
AUDIO   = "Sadar.m4a"

resp = requests.post(
    "https://api.deepgram.com/v1/listen",
    params={
        "model": "nova-3",
        "smart_format": "true",
        "punctuate": "true",
        "diarize": "true",
        "utterances": "true",
    },
    headers={
        "Authorization": f"Token {API_KEY}",
        "Content-Type": "audio/mp4",   # use audio/wav for .wav, audio/mp4 for .m4a
    },
    data=open(AUDIO, "rb").read(),
    timeout=300,
)
resp.raise_for_status()
out = resp.json()

json.dump(out, open("dg_out.json", "w"), indent=2)

words = out["results"]["channels"][0]["alternatives"][0]["words"]
for w in words[:8]:
    print(w)