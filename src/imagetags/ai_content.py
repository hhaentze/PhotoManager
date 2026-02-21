import ollama

describe_content = """
You are a computer agent. Your task is to generate a concise file name for an image based on its content.

Follow these rules strictly:
1. The file name must be 2 or 3 words long.
2. Words must uniquely and descriptively summarize the visual content of the image.
3. Include the word "selfie" only if the image is primarily a close-up of a single person taken by themselves.
4. If it is a group picture, include the word "group."
5. Use underscores (_) to separate words, e.g., word1_word2.
6. Do not repeat words.
7. Ignore text or writing in the image, as well as any numbers, dates, or times.
8. Avoid these words: tourists, man, woman.
9. Do not use special characters, symbols, or quotation marks.

After generating the file name, double-check to ensure it complies with all rules. Output only the final shortened file name. Do not explain your reasoning or add extra information.
"""

describe_content2 = """
Describe the image in 2 to 4 words.

Follow these rules strictly:
1. Never use more than 4 words
2. Words must uniquely and descriptively summarize the visual content of the image.
3. Include the word "selfie" only if the image is primarily a close-up of a single person taken by themselves.
4. If it is a group picture, include the word "group."
6. Do not repeat words.
7. Ignore text or writing in the image, as well as any numbers, dates, or times.
8. Avoid these words: tourists, man, woman.
9. Do not use special characters, symbols, or quotation marks.
"""


def generate_filename(img_path: str, prompt: str, model: str = "llava:13b") -> str:
    response = ollama.generate(model=model, prompt=prompt, images=[img_path], stream=False)["response"]
    response = response.strip()
    return response
