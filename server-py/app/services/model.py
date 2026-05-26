# 模型工厂：统一创建模型实例，业务代码不直接 new
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ..config import config


def create_chat_model(temperature=0.7, streaming=False, callbacks=None):
    instance = ChatOpenAI(
        model=config['ai']['primary_model'],
        api_key=config['ai']['deepseek_key'],
        base_url=config['ai']['base_url'],
        temperature=temperature,
        streaming=streaming,
        callbacks=callbacks or [],
        timeout=30,
    )
    # DeepSeek 与 gpt-3.5-turbo 同用 cl100k_base 编码
    instance.model_name = 'gpt-3.5-turbo'
    return instance


def create_embeddings():
    return OpenAIEmbeddings(
        model='deepseek-embedding',
        api_key=config['ai']['deepseek_key'],
        base_url=config['ai']['base_url'],
    )


# 单例
chat_model = create_chat_model(temperature=0.7, streaming=True)
embeddings = create_embeddings()
