import sys
from configuration import config

# 将 uie_pytorch 加入路径
sys.path.insert(0, str(config.ROOT_DIR / 'uie_pytorch'))
from uie_pytorch.uie_predictor import UIEPredictor


class EntityExtractorModelBase:
    """实体抽取-基于模型:使用 UIE 抽取实体"""

    def __init__(self, model_params_path, device="cpu", batch_size=8):
        # 初始化 UIE
        self.uie = UIEPredictor(
            model="uie-base",
            task_path=model_params_path,
            schema=[],
            engine="pytorch",
            device=device,
            batch_size=batch_size,
        )

    def __call__(self, text, schema):
        self.uie.set_schema(schema)
        res: list[dict] = []
        # 统一转换为列表
        input_texts = text if isinstance(text, list) else [text]
        res = self.uie(input_texts)
        for one_res in res:
            for k, values in one_res.items():
                one_res[k] = list({v["text"] for v in values})
        return res if isinstance(text, list) else res[0]


if __name__ == "__main__":
    model_params_path = config.ROOT_DIR / 'finetuned' / 'checkpoint' / 'model_best'
    eerb = EntityExtractorModelBase(model_params_path)
    res = eerb(
        "编程技术下有人工智能相关的学科吗",
        ["分类", "学科", "课程", "章节", "试题", "知识点"],
    )
    print(res)
