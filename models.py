"""数据模型"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class WebTestCase(db.Model):
    """Web 平台的测试用例表（独立于 Trae CLI 写入的 test_case 表）"""
    __tablename__ = "web_test_case"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    test_point_id = db.Column(db.Integer, db.ForeignKey("test_point.id"), nullable=True)
    status = db.Column(db.String(20), default="draft")  # draft(草稿) / adopted(采纳) / archived(归档)
    title = db.Column(db.String(500), nullable=False, default="")
    priority = db.Column(db.String(20), default="")
    owner = db.Column(db.String(100), default="")
    tags = db.Column(db.String(500), default="")
    project = db.Column(db.String(200), default="")
    case_set = db.Column(db.String(200), default="")
    case_type = db.Column(db.String(50), default="")
    precondition = db.Column(db.Text)
    steps = db.Column(db.Text)
    expected = db.Column(db.Text)
    evidence_source = db.Column(db.String(500), default="")
    evidence_level = db.Column(db.String(10), default="")
    evi_block_ids = db.Column(db.String(500), default="")
    doc_name = db.Column(db.String(500), default="")
    doc_version = db.Column(db.String(100), default="")
    source = db.Column(db.String(20), default="manual")   # manual/import/ai
    # status = db.Column(db.String(20), default="active")
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    case_set_id = db.Column(db.Integer, db.ForeignKey("case_set.id"), nullable=True)
    requirement_doc_id = db.Column(db.Integer, db.ForeignKey("requirement_doc.id"), nullable=True)
    # 建立一对多关系（级联删除）
    evidences = db.relationship('Evidence', backref='test_case', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority,
            "owner": self.owner,
            "tags": self.tags,
            "project": self.project,
            "case_set": self.case_set,
            "case_type": self.case_type,
            "precondition": self.precondition,
            "steps": self.steps,
            "expected": self.expected,
            "evidence_source": self.evidence_source,
            "evidence_level": self.evidence_level,
            "evi_block_ids": self.evi_block_ids,
            "doc_name": self.doc_name,
            "doc_version": self.doc_version,
            "source": self.source,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
        }
class CaseSet(db.Model):
    """用例集（树形，支持无限层级）"""
    __tablename__ = "case_set"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("case_set.id"), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    children = db.relationship(
        "CaseSet",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "sort_order": self.sort_order,
        }


class RequirementDoc(db.Model):
    """需求文档存档"""
    __tablename__ = "requirement_doc"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    doc_name = db.Column(db.String(500), nullable=False)
    doc_version = db.Column(db.String(100), default="")
    file_path = db.Column(db.String(500), default="")     # 上传的 docx 路径
    uploaded_at = db.Column(db.DateTime, default=datetime.now)


class Evidence(db.Model):
    """证据事实实体（一等公民）"""
    __tablename__ = "evidence"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    test_case_id = db.Column(db.Integer, db.ForeignKey("web_test_case.id"), nullable=False)

    # 锚定关联
    source_block_id = db.Column(db.Integer, nullable=True)
    quote = db.Column(db.Text)  # 原文片段（从 SourceBlock 截取）
    content_hash = db.Column(db.String(64), nullable=True)  # 校验哈希

    # 可选扩展字段
    evidence_level = db.Column(db.String(10), default="")
    parser_version = db.Column(db.String(20), default="v1.0")

    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "source_block_id": self.source_block_id,
            "quote": self.quote,
            "evidence_level": self.evidence_level,
        }

class TestPoint(db.Model):
    """测试点（一等实体）"""
    __tablename__ = "test_point"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    requirement_doc_id = db.Column(db.Integer, db.ForeignKey("requirement_doc.id"), nullable=True)
    is_attention = db.Column(db.Boolean, default=False) # 是否为需关注的高风险/推测测试点
    content = db.Column(db.Text, nullable=False)  # 测试点描述
    intent = db.Column(db.Text, default="")  # 测试意图
    scene = db.Column(db.String(100), default="通用场景") # 所属场景
    method = db.Column(db.String(50), default="") # 测试设计方法（如：场景法、边界值）
    category = db.Column(db.String(50), default="功能")  # 功能/边界/异常等
    priority = db.Column(db.String(20), default="P1")
    evidence_ids = db.Column(db.String(200), default="")  # 关联的证据块
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected

    # 专家评审结果
    expert_opinion = db.Column(db.String(50), default="") # 建议通过 / 建议拒绝 / 不确定
    expert_advice = db.Column(db.Text, default="")        # 具体的修改建议
    expert_name = db.Column(db.String(100), default="")   # 评审专家名称
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "intent": self.intent,  # <--- 补上测试意图
            "category": self.category,
            "priority": self.priority,
            "evidence_ids": self.evidence_ids,
            "status": self.status,
            "scene": self.scene,
            "method": self.method,
            "is_attention": self.is_attention,
            "expert_opinion": self.expert_opinion,
            "expert_advice": self.expert_advice,
            "expert_name": self.expert_name
        }

class Expert(db.Model):
    """专家团队（异构模型配置）"""
    __tablename__ = "expert"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(50), default="🤖") #记录专家的头像
    language = db.Column(db.String(20), default="中文") #回复语言
    description = db.Column(db.String(200), default="")
    model_name = db.Column(db.String(100), default="GLM-5.3") # 指定底层大模型
    soul_md = db.Column(db.Text) # 灵魂设定 (Prompt)
    created_at = db.Column(db.DateTime, default=datetime.now)