import torch
import torch.functional as F
import torch.distributed as dist
import numpy as np
from einops import rearrange

from lightllm.models.bloom.layer_weights.pre_and_post_layer_weight import PreAndPostLayerWeight
from lightllm.models.bloom.layer_infer.infer_struct import InferStateInfo
from lightllm.utils.infer_utils import mark_cost_time
from lightllm.models.bloom.triton_kernel.layernorm import layernorm_forward

torch.backends.cudnn.enabled = True


class PreLayerInfer:
    """
    """

    def __init__(self, tp_rank, world_size, network_config):
        self.tp_rank_ = tp_rank
        self.world_size_ = world_size
        self.network_config_ = network_config
        assert (network_config["vocab_size"] % self.world_size_ == 0)
        self.tp_vocab_size_ = network_config["vocab_size"] // self.world_size_
        self.embed_dim_ = network_config["n_embed"]
        self.layer_norm_eps_ = network_config["layer_norm_epsilon"]
        self.vob_start_id_ = self.tp_vocab_size_ * self.tp_rank_
        self.vob_end_id_ = self.tp_vocab_size_ * (self.tp_rank_ + 1)

    @mark_cost_time("pre context forward")  # dont to remove this, will make performence down, did not know why
    def context_forward(self, input_ids, infer_state: InferStateInfo, layer_weight: PreAndPostLayerWeight):
        total_token_num = infer_state.total_token_num
        input_ids = input_ids[0:total_token_num]

        input_mask = torch.logical_or(self.vob_start_id_ > input_ids, input_ids >= self.vob_end_id_)
        tmp_input_ids = (input_ids - self.vob_start_id_)
        tmp_input_ids[input_mask] = 0
        input_embdings = torch.embedding(layer_weight.wte_weight_, tmp_input_ids, padding_idx=-1)
        input_embdings[input_mask] = 0.0
        if self.world_size_ > 1:
            dist.all_reduce(input_embdings, op=dist.ReduceOp.SUM, async_op=False)
        input_embdings = layernorm_forward(
            input_embdings,
            layer_weight.pre_layernorm_weight_,
            layer_weight.pre_layernorm_bias_,
            eps=self.layer_norm_eps_)
        return input_embdings

    def token_forward(self, input_ids, infer_state: InferStateInfo, layer_weight: PreAndPostLayerWeight):
        input_mask = torch.logical_or(self.vob_start_id_ > input_ids, input_ids >= self.vob_end_id_)
        tmp_input_ids = (input_ids - self.vob_start_id_)
        tmp_input_ids[input_mask] = 0
        input_embdings = torch.embedding(layer_weight.wte_weight_, tmp_input_ids, padding_idx=-1)
        input_embdings[input_mask] = 0.0
        if self.world_size_ > 1:
            dist.all_reduce(input_embdings, op=dist.ReduceOp.SUM, async_op=False)
        input_embdings = layernorm_forward(
            input_embdings,
            layer_weight.pre_layernorm_weight_,
            layer_weight.pre_layernorm_bias_,
            eps=self.layer_norm_eps_)

        return input_embdings
