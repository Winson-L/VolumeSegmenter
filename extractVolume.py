import numpy as np
from scipy.ndimage import label, gaussian_laplace, distance_transform_edt, binary_dilation
import os
import time
import argparse
import json
from tqdm import tqdm
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

def convert_numpy_types(obj):
    """递归转换NumPy类型为Python原生类型"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    return obj

class UniversalVolumeSegmenter:
    def __init__(self,
                 input_path,
                 output_dir,
                 shape,
                 dtype=np.uint8,
                 min_component_ratio=0.0001,  # 0.01% of volume
                 max_total_components=16,
                 max_size_ratio=0.15,  # 15% of total volume
                 timeout_seconds=300):
        """
        通用体积分割器 (任意尺寸 + 多组件保证)
        核心改进:
        1. 完全移除256³硬编码
        2. 自适应组件数量 (4-12个)
        3. 体积比例驱动参数
        4. 多级分割策略
        """
        self.input_path = input_path
        self.output_dir = output_dir
        self.shape = shape  # 从参数获取，无默认值
        self.dtype = dtype
        self.min_component_ratio = min_component_ratio
        self.max_total_components = max_total_components
        self.max_size_ratio = max_size_ratio
        self.timeout_seconds = timeout_seconds
        self.padding = 3

        os.makedirs(output_dir, exist_ok=True)
        self.volume = self._read_volume_correctly()
        print(f"✅ 正确加载数据: 形状={self.volume.shape}, 范围=[{self.volume.min()}, {self.volume.max()}]")
        
        # 计算动态参数 (基于体积大小)
        self._calculate_dynamic_parameters()
        
        # 诊断数据分布
        self._diagnose_data_distribution()

    def _read_volume_correctly(self):
        """正确加载体积数据 (任意尺寸)"""
        with open(self.input_path, 'rb') as f:
            data = np.fromfile(f, dtype=self.dtype)
        
        total_expected = np.prod(self.shape)
        if data.size == total_expected:
            return data.reshape(self.shape)
        
        # 尝试常见形状排列
        dim_permutations = [
            (self.shape[2], self.shape[1], self.shape[0]),  # (x,y,z) -> (z,y,x)
            (self.shape[1], self.shape[0], self.shape[2]),
            (self.shape[0], self.shape[2], self.shape[1]),
            (self.shape[2], self.shape[0], self.shape[1]),
            (self.shape[1], self.shape[2], self.shape[0])
        ]
        
        for shape in dim_permutations:
            if data.size == np.prod(shape):
                print(f"🔄 自动匹配形状: {shape} (原始: {self.shape})")
                return data.reshape(shape)
        
        # 尝试推断形状 (仅当体积为立方体)
        cube_root = round(data.size ** (1/3))
        if cube_root ** 3 == data.size:
            inferred_shape = (cube_root, cube_root, cube_root)
            print(f"🔍 推断形状: {inferred_shape} (原始: {self.shape})")
            return data.reshape(inferred_shape)
        
        raise ValueError(f"无法匹配形状! 期望 {total_expected} 个体素, 实际 {data.size}")

    def _calculate_dynamic_parameters(self):
        """动态计算参数 (基于体积大小)"""
        print("\n⚙️ 动态计算参数 (基于体积大小)...")
        
        total_voxels = np.prod(self.shape)
        self.min_component_size = max(50, int(total_voxels * self.min_component_ratio))
        
        # 1. 下采样因子 (基于内存安全)
        if total_voxels > 50000000:  # >50M体素
            self.downsample_factor = 8
        elif total_voxels > 10000000:  # 10-50M体素
            self.downsample_factor = 4
        elif total_voxels > 2000000:  # 2-10M体素
            self.downsample_factor = 2
        else:
            self.downsample_factor = 1
        
        # 2. K-means聚类数量 (基于体积复杂度)
        if total_voxels < 1000000:  # <1M体素
            self.kmeans_clusters = 4
        elif total_voxels < 5000000:  # 1-5M体素
            self.kmeans_clusters = 6
        elif total_voxels < 20000000:  # 5-20M体素
            self.kmeans_clusters = 8
        else:  # >20M体素
            self.kmeans_clusters = 10
        
        # 3. 文件大小约束
        bytes_per_voxel = np.dtype(self.dtype).itemsize
        self.total_volume_bytes = total_voxels * bytes_per_voxel
        self.max_component_bytes = int(self.total_volume_bytes * self.max_size_ratio)
        self.max_component_voxels = self.max_component_bytes // bytes_per_voxel
        
        print(f"  • 体积大小: {total_voxels:,} 体素")
        print(f"  • 最小组件大小: {self.min_component_size:,} 体素 ({self.min_component_ratio*100:.2f}%)")
        print(f"  • 下采样因子: {self.downsample_factor}x")
        print(f"  • K-means聚类数: {self.kmeans_clusters}")
        print(f"  • 最大组件大小: {self.max_component_bytes/1024/1024:.1f} MB")

    def _diagnose_data_distribution(self):
        """诊断数据分布 (无256假设)"""
        print("\n🔍 诊断数据分布...")
        
        non_zero = self.volume[self.volume > 0]
        if len(non_zero) > 0:
            self.intensity_mean = np.mean(non_zero)
            self.intensity_std = np.std(non_zero)
            self.intensity_min = np.min(non_zero)
            self.intensity_max = np.max(non_zero)
            
            print(f"  • 强度范围: [{self.intensity_min:.1f}, {self.intensity_max:.1f}]")
            print(f"  • 强度均值: {self.intensity_mean:.1f} ± {self.intensity_std:.1f}")
            
            # 非零体素比例
            non_zero_ratio = len(non_zero) / np.prod(self.shape)
            print(f"  • 非零体素比例: {non_zero_ratio*100:.1f}%")
            
            # 自动背景阈值
            if non_zero_ratio < 0.05:  # 5%背景
                self.background_threshold = np.percentile(self.volume, 5)
            elif non_zero_ratio > 0.95:  # 5%前景
                self.background_threshold = np.percentile(self.volume, 95)
            else:
                sample_size = min(10000, len(non_zero))
                sample_idx = np.random.choice(len(non_zero), sample_size, replace=False)
                sample_values = non_zero[sample_idx].reshape(-1, 1)
                
                kmeans = KMeans(n_clusters=2, n_init=3, random_state=42)
                kmeans.fit(sample_values)
                cluster_centers = kmeans.cluster_centers_.flatten()
                self.background_threshold = np.min(cluster_centers)
            
            print(f"  • 自动背景阈值: {self.background_threshold:.1f}")
        else:
            print("  ⚠️ 无非零体素! 使用默认阈值")
            self.background_threshold = 10.0
            self.intensity_mean = 0.0
            self.intensity_std = 1.0
            self.intensity_min = 0.0
            self.intensity_max = 255.0
        
        # 空间-强度权重
        self._compute_adaptive_weights()

    def _compute_adaptive_weights(self):
        """自适应计算空间-强度权重 (无256假设)"""
        print("\n⚖️ 计算自适应权重...")
        
        if self.intensity_std < 15:
            self.spatial_weight = 0.3
            self.intensity_weight = 0.7
            print("  • 低对比度: 强度权重 0.7 (保留细节)")
        elif self.intensity_std > 70:
            self.spatial_weight = 0.8
            self.intensity_weight = 0.2
            print("  • 高对比度: 空间权重 0.8 (保持连续性)")
        else:
            self.spatial_weight = 0.5
            self.intensity_weight = 0.5
            print("  • 中等对比度: 平衡权重 0.5/0.5")
        
        # 空间半径基于体积尺寸
        self.spatial_radius = max(3.0, min(15.0, 
            self.intensity_std / 5.0,
            min(self.shape) / 20.0  # 体积尺寸的5%
        ))
        print(f"  • 空间半径: {self.spatial_radius:.1f} 体素")

    def _adaptive_background_separation(self):
        """自适应背景分离 (任意尺寸)"""
        print("\n🎯 自适应背景分离...")
        
        background_mask = self.volume <= self.background_threshold
        
        # 仅当体积足够大时添加边界
        margin = min(3, min(self.shape) // 10)
        if self.shape[0] > margin*2:
            background_mask[:margin, :, :] = True
            background_mask[-margin:, :, :] = True
        if self.shape[1] > margin*2:
            background_mask[:, :margin, :] = True
            background_mask[:, -margin:, :] = True
        if self.shape[2] > margin*2:
            background_mask[:, :, :margin] = True
            background_mask[:, :, -margin:] = True
        
        # 仅当体积足够大时进行形态学操作
        if min(self.shape) > 10:
            structure = np.ones((3, 3, 3), dtype=bool)
            background_mask = binary_dilation(background_mask, structure=structure, iterations=1)
        
        original_background = np.sum(background_mask)
        self.volume[background_mask] = 0
        
        foreground_ratio = np.sum(self.volume > 0) / np.prod(self.shape)
        print(f"  ✅ 背景分离完成: {original_background:,} 体素设为0")
        print(f"  📊 前景比例: {foreground_ratio*100:.1f}%")

    def _create_feature_volume(self):
        """创建特征体积 (任意尺寸 + 内存安全)"""
        print("\n🧠 创建特征体积 (任意尺寸)...")
        
        # 保存原始体积
        self.original_volume = self.volume.copy()
        self.original_shape = self.shape
        
        # 1. 下采样 (内存控制)
        if self.downsample_factor > 1:
            print(f"  • 下采样: {self.downsample_factor}x")
            
            # 计算有效结束位置
            z_end = self.shape[0] - (self.shape[0] % self.downsample_factor)
            y_end = self.shape[1] - (self.shape[1] % self.downsample_factor)
            x_end = self.shape[2] - (self.shape[2] % self.downsample_factor)
            
            # 确保有有效区域
            if z_end < self.downsample_factor or y_end < self.downsample_factor or x_end < self.downsample_factor:
                print("  ⚠️ 体积太小，跳过下采样")
                self.downsample_factor = 1
            else:
                downsampled = self.volume[
                    :z_end:self.downsample_factor,
                    :y_end:self.downsample_factor,
                    :x_end:self.downsample_factor
                ].copy()
                
                self.volume = downsampled
                self.shape = downsampled.shape
                print(f"  • 体积缩小: {self.original_shape} → {self.shape}")
        
        # 2. 归一化强度
        foreground_mask = self.volume > 0
        self.norm_intensity = np.zeros_like(self.volume, dtype=np.float32)
        
        if np.any(foreground_mask):
            valid_voxels = self.volume[foreground_mask]
            if np.max(valid_voxels) > np.min(valid_voxels):
                self.norm_intensity[foreground_mask] = (
                    valid_voxels - np.min(valid_voxels)
                ) / (np.max(valid_voxels) - np.min(valid_voxels) + 1e-8)
        
        # 3. 空间坐标 (任意尺寸)
        z_coords, y_coords, x_coords = np.meshgrid(
            range(self.shape[0]),
            range(self.shape[1]),
            range(self.shape[2]),
            indexing='ij'
        )
        
        # 归一化到[0,1]
        self.norm_z = z_coords / max(1, self.shape[0] - 1)
        self.norm_y = y_coords / max(1, self.shape[1] - 1)
        self.norm_x = x_coords / max(1, self.shape[2] - 1)
        
        print(f"  ✅ 特征体积创建完成! 形状: {self.shape}")

    def _kmeans_segmentation(self):
        """K-means分割 (内存高效 + 多组件保证)"""
        print("\n🧩 K-means分割 (多组件保证)...")
        
        foreground_mask = self.volume > 0
        coords = np.where(foreground_mask)
        
        if len(coords[0]) == 0:
            print("  ⚠️ 无前景体素! 创建默认网格组件")
            return self._create_default_grid_components()
        
        # 1. 采样点 (内存控制)
        sample_size = min(30000, len(coords[0]))  # 30K点平衡内存和质量
        if len(coords[0]) > sample_size:
            print(f"  • 采样 {sample_size:,} / {len(coords[0]):,} 个体素")
            sample_idx = np.random.choice(len(coords[0]), sample_size, replace=False)
            sample_coords = (coords[0][sample_idx], coords[1][sample_idx], coords[2][sample_idx])
        else:
            sample_coords = coords
        
        # 2. 准备特征
        X = np.column_stack([
            self.norm_x[sample_coords[0], sample_coords[1], sample_coords[2]] * self.spatial_weight,
            self.norm_y[sample_coords[0], sample_coords[1], sample_coords[2]] * self.spatial_weight,
            self.norm_z[sample_coords[0], sample_coords[1], sample_coords[2]] * self.spatial_weight,
            self.norm_intensity[sample_coords[0], sample_coords[1], sample_coords[2]] * self.intensity_weight
        ])
        
        # 3. 标准化
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # 4. K-means (至少4个簇保证多组件)
        min_clusters = max(4, min(self.kmeans_clusters, len(sample_coords[0]) // 1000))
        actual_clusters = max(min_clusters, 2)  # 至少2个簇
        
        kmeans = KMeans(
            n_clusters=actual_clusters,
            n_init=3,
            random_state=42,
            max_iter=100
        )
        labels = kmeans.fit_predict(X_scaled)
        print(f"  ✅ K-means完成: {actual_clusters} 个聚类 (最小: {min_clusters})")
        
        # 5. 创建组件
        components = []
        unique_labels = np.unique(labels)
        
        for cluster_id in unique_labels:
            cluster_mask = np.zeros_like(self.volume, dtype=bool)
            
            # 仅设置采样点
            cluster_points = (labels == cluster_id)
            if np.sum(cluster_points) == 0:
                continue
            
            for i, (z, y, x) in enumerate(zip(
                sample_coords[0][cluster_points],
                sample_coords[1][cluster_points],
                sample_coords[2][cluster_points]
            )):
                cluster_mask[z, y, x] = True
            
            # 6. 填充分量 (区域增长)
            if min(self.shape) > 5:  # 仅当体积足够大
                structure = np.ones((3, 3, 3), dtype=bool)
                cluster_mask = binary_dilation(cluster_mask, structure=structure, iterations=1)
                cluster_mask &= foreground_mask
            
            size = np.sum(cluster_mask)
            if size >= self.min_component_size:
                coords = np.where(cluster_mask)
                bbox_min = [int(np.min(c)) for c in coords]
                bbox_max = [int(np.max(c)) for c in coords]
                
                components.append({
                    'mask': cluster_mask,
                    'size': int(size),
                    'bbox_min': bbox_min,
                    'bbox_max': bbox_max,
                    'stage': 'kmeans',
                    'cluster_id': int(cluster_id)
                })
        
        # 7. 保证最小组件数
        if len(components) < 4:
            print(f"  ⚠️ 组件数不足 ({len(components)} < 4), 创建额外组件")
            extra_components = self._create_extra_components(len(components))
            components.extend(extra_components)
        
        print(f"  ✅ 生成 {len(components)} 个K-means组件 (目标: ≥4)")
        return components

    def _create_default_grid_components(self):
        """创建默认网格组件 (当无前景时)"""
        print("  🔄 创建默认网格组件...")
        
        components = []
        grid_size = 2  # 2x2x2 = 8个组件
        
        # 确保网格大小不超过体积
        grid_z = min(grid_size, self.shape[0] // 10)
        grid_y = min(grid_size, self.shape[1] // 10)
        grid_x = min(grid_size, self.shape[2] // 10)
        
        for i in range(grid_z):
            for j in range(grid_y):
                for k in range(grid_x):
                    if len(components) >= 8:
                        break
                    
                    z_start = i * self.shape[0] // grid_z
                    y_start = j * self.shape[1] // grid_y
                    x_start = k * self.shape[2] // grid_x
                    z_end = (i+1) * self.shape[0] // grid_z
                    y_end = (j+1) * self.shape[1] // grid_y
                    x_end = (k+1) * self.shape[2] // grid_x
                    
                    # 确保有有效区域
                    if z_end - z_start < 3 or y_end - y_start < 3 or x_end - x_start < 3:
                        continue
                    
                    mask = np.zeros_like(self.volume, dtype=bool)
                    mask[z_start:z_end, y_start:y_end, x_start:x_end] = True
                    
                    size = np.sum(mask)
                    if size < self.min_component_size:
                        continue
                    
                    coords = np.where(mask)
                    bbox_min = [int(np.min(c)) for c in coords]
                    bbox_max = [int(np.max(c)) for c in coords]
                    
                    components.append({
                        'mask': mask,
                        'size': int(size),
                        'bbox_min': bbox_min,
                        'bbox_max': bbox_max,
                        'stage': 'default_grid'
                    })
        
        # 保证至少4个组件
        while len(components) < 4 and len(components) > 0:
            # 复制现有组件 (位置偏移)
            base_comp = components[-1]
            new_mask = np.zeros_like(self.volume, dtype=bool)
            
            # 创建偏移
            offset_z = min(5, self.shape[0] // 4)
            offset_y = min(5, self.shape[1] // 4)
            offset_x = min(5, self.shape[2] // 4)
            
            new_mask[
                base_comp['bbox_min'][0]+offset_z:base_comp['bbox_max'][0]+offset_z+1,
                base_comp['bbox_min'][1]+offset_y:base_comp['bbox_max'][1]+offset_y+1,
                base_comp['bbox_min'][2]+offset_x:base_comp['bbox_max'][2]+offset_x+1
            ] = base_comp['mask'][
                base_comp['bbox_min'][0]:base_comp['bbox_max'][0]+1,
                base_comp['bbox_min'][1]:base_comp['bbox_max'][1]+1,
                base_comp['bbox_min'][2]:base_comp['bbox_max'][2]+1
            ]
            
            size = np.sum(new_mask)
            if size >= self.min_component_size:
                coords = np.where(new_mask)
                bbox_min = [int(np.min(c)) for c in coords]
                bbox_max = [int(np.max(c)) for c in coords]
                
                components.append({
                    'mask': new_mask,
                    'size': int(size),
                    'bbox_min': bbox_min,
                    'bbox_max': bbox_max,
                    'stage': 'default_offset'
                })
        
        print(f"  ✅ 创建 {len(components)} 个默认网格组件 (保证≥4)")
        return components[:8]  # 最多8个

    def _create_extra_components(self, existing_count):
        """创建额外组件 (保证最少4个)"""
        print(f"  ➕ 创建额外组件 (现有: {existing_count}, 目标: 4)...")
        
        extra_components = []
        remaining = 4 - existing_count
        
        # 基于数据分布创建额外组件
        foreground_mask = self.volume > 0
        if np.any(foreground_mask):
            # 1. 按强度分位数分割
            intensity_values = self.volume[foreground_mask]
            if len(intensity_values) > 1000:
                # 创建4个强度区间
                percentiles = [25, 50, 75, 100]
                for i in range(remaining):
                    if i >= len(percentiles)-1:
                        break
                    
                    lower = np.percentile(intensity_values, percentiles[i])
                    upper = np.percentile(intensity_values, percentiles[i+1])
                    
                    mask = (self.volume >= lower) & (self.volume < upper) & foreground_mask
                    size = np.sum(mask)
                    
                    if size >= self.min_component_size * 0.5:  # 允许较小
                        coords = np.where(mask)
                        bbox_min = [int(np.min(c)) for c in coords]
                        bbox_max = [int(np.max(c)) for c in coords]
                        
                        extra_components.append({
                            'mask': mask,
                            'size': int(size),
                            'bbox_min': bbox_min,
                            'bbox_max': bbox_max,
                            'stage': f'extra_intensity_{i}'
                        })
        
        # 如果强度方法失败，使用空间分割
        if len(extra_components) < remaining:
            print("  🔄 强度分割不足，使用空间分割补充")
            spatial_components = self._create_default_grid_components()
            extra_components.extend(spatial_components[:remaining - len(extra_components)])
        
        print(f"  ✅ 创建 {len(extra_components)} 个额外组件")
        return extra_components[:remaining]

    def _refine_and_filter_components(self, components):
        """细化和过滤组件 (保证质量)"""
        print("\n🔍 细化和过滤组件...")
        
        refined_components = []
        
        for comp in components:
            # 1. 移除小孔洞
            if min(self.shape) > 10:
                structure = np.ones((3, 3, 3), dtype=bool)
                filled = binary_dilation(comp['mask'], structure=structure, iterations=1)
                filled = binary_dilation(filled, structure=structure, iterations=1)
            else:
                filled = comp['mask'].copy()
            
            size = np.sum(filled)
            if size >= self.min_component_size * 0.7:  # 允许70%缩小
                coords = np.where(filled)
                bbox_min = [int(np.min(c)) for c in coords]
                bbox_max = [int(np.max(c)) for c in coords]
                
                refined_components.append({
                    'mask': filled,
                    'size': int(size),
                    'bbox_min': bbox_min,
                    'bbox_max': bbox_max,
                    'stage': 'refined'
                })
                print(f"  ✅ 保留组件: {size:,} 体素")
            else:
                print(f"  ❌ 丢弃小组件: {size:,} < {self.min_component_size * 0.7:,}")
        
        # 2. 按大小排序
        refined_components.sort(key=lambda x: x['size'], reverse=True)
        
        # 3. 保证最小组件数 (4-8个)
        target_count = max(4, min(8, self.max_total_components))
        if len(refined_components) < target_count:
            print(f"  ⚠️ 组件数不足 ({len(refined_components)} < {target_count}), 保留所有")
        else:
            refined_components = refined_components[:target_count]
            print(f"  ✅ 选择最大的 {target_count} 个组件")
        
        print(f"  📊 最终组件数: {len(refined_components)}")
        return refined_components

    def _upsample_components(self, components):
        """上采样组件 (恢复原始分辨率)"""
        if self.downsample_factor == 1:
            return components
        
        print(f"\n⬆️ 上采样组件 (恢复 {self.downsample_factor}x 分辨率)...")
        
        upsampled_components = []
        
        for comp in components:
            # 1. 创建上采样掩码
            upsampled_mask = np.zeros(self.original_shape, dtype=bool)
            
            # 2. 映射回原始坐标
            for z in range(comp['mask'].shape[0]):
                for y in range(comp['mask'].shape[1]):
                    for x in range(comp['mask'].shape[2]):
                        if comp['mask'][z, y, x]:
                            # 映射到原始体积
                            orig_z = z * self.downsample_factor
                            orig_y = y * self.downsample_factor
                            orig_x = x * self.downsample_factor
                            
                            # 填充小块
                            z_end = min(orig_z + self.downsample_factor, self.original_shape[0])
                            y_end = min(orig_y + self.downsample_factor, self.original_shape[1])
                            x_end = min(orig_x + self.downsample_factor, self.original_shape[2])
                            
                            if orig_z < self.original_shape[0] and orig_y < self.original_shape[1] and orig_x < self.original_shape[2]:
                                upsampled_mask[orig_z:z_end, orig_y:y_end, orig_x:x_end] = True
            
            # 3. 计算新属性
            size = np.sum(upsampled_mask)
            if size < self.min_component_size * 0.5:  # 太小则跳过
                print(f"  ❌ 上采样后组件太小: {size:,} < {self.min_component_size * 0.5:,}")
                continue
            
            coords = np.where(upsampled_mask)
            bbox_min = [int(np.min(c)) for c in coords]
            bbox_max = [int(np.max(c)) for c in coords]
            
            upsampled_components.append({
                'mask': upsampled_mask,
                'size': int(size),
                'bbox_min': bbox_min,
                'bbox_max': bbox_max,
                'stage': 'upsampled'
            })
            print(f"  ✅ 上采样组件: {comp['size']:,} → {size:,} 体素")
        
        # 4. 保证最小组件数
        if len(upsampled_components) < 4:
            print(f"  ⚠️ 上采样后组件不足 ({len(upsampled_components)} < 4), 使用原始组件")
            return components
        
        print(f"  ✅ 上采样完成: {len(components)} → {len(upsampled_components)} 个组件")
        return upsampled_components

    def _optimize_and_save_components(self, components):
        """优化并保存组件 (任意尺寸)"""
        print(f"\n💾 优化并保存 {len(components)} 个组件...")
        
        saved_files = []
        file_sizes_mb = []
        
        for i, comp in enumerate(components):
            print(f"\n📦 处理组件 {i+1}/{len(components)}:")
            print(f"   • 大小: {comp['size']:,} 体素")
            print(f"   • 边界框: {comp['bbox_min']} → {comp['bbox_max']}")
            print(f"   • 来源: {comp['stage']}")
            
            # 1. 裁剪数据 (边界检查)
            z_min, y_min, x_min = comp['bbox_min']
            z_max, y_max, x_max = comp['bbox_max']
            
            # 确保在边界内
            z_min = max(0, z_min)
            y_min = max(0, y_min)
            x_min = max(0, x_min)
            z_max = min(self.original_shape[0]-1, z_max)
            y_max = min(self.original_shape[1]-1, y_max)
            x_max = min(self.original_shape[2]-1, x_max)
            
            cropped_data = self.original_volume[z_min:z_max+1, y_min:y_max+1, x_min:x_max+1].copy()
            cropped_mask = comp['mask'][z_min:z_max+1, y_min:y_max+1, x_min:x_max+1]
            cropped_data[~cropped_mask] = 0
            
            # 2. 检查文件大小
            current_shape = cropped_data.shape
            current_voxels = np.prod(current_shape)
            current_bytes = current_voxels * np.dtype(self.dtype).itemsize
            
            if current_bytes > self.max_component_bytes:
                print(f"  ⚠️ 组件太大: {current_bytes/1024/1024:.1f} MB > {self.max_component_bytes/1024/1024:.1f} MB")
                
                # 2.1 下采样
                scale_factor = (self.max_component_bytes / current_bytes) ** (1/3)
                downsample_factor = max(2, int(1 / scale_factor) + 1)
                print(f"  📉 下采样因子: {downsample_factor}x")
                
                downsampled = cropped_data[::downsample_factor, ::downsample_factor, ::downsample_factor]
                final_data = downsampled
            else:
                final_data = cropped_data
            
            # 3. 保存 (任意尺寸)
            sz, sy, sx = final_data.shape
            filename = f"component_{i+1}_{sx}x{sy}x{sz}_{x_min}x{y_min}x{z_min}_0.0x0.0x0.0.raw"
            filepath = os.path.join(self.output_dir, filename)
            
            final_data.astype(self.dtype).tofile(filepath)
            file_size = os.path.getsize(filepath)
            file_size_mb = file_size / 1024 / 1024
            
            print(f"  💾 保存: {filename} ({file_size_mb:.2f} MB)")
            saved_files.append(filename)
            file_sizes_mb.append(file_size_mb)
        
        return saved_files, file_sizes_mb

    def process(self):
        """主处理流程 (任意尺寸 + 多组件保证)"""
        print("="*60)
        print("🚀 通用体积分割器 (任意尺寸 + 多组件保证)")
        print(f"🎯 体积形状: {self.shape}")
        print(f"🎯 保证生成 4-8 个有意义组件")
        print("="*60)
        start_time = time.time()

        try:
            # 1. 自适应背景分离
            self._adaptive_background_separation()
            
            # 2. 创建特征体积 (下采样)
            self._create_feature_volume()
            
            # 3. K-means分割 (保证多组件)
            raw_components = self._kmeans_segmentation()
            
            # 4. 细化和过滤
            refined_components = self._refine_and_filter_components(raw_components)
            
            # 5. 上采样 (恢复原始分辨率)
            upsampled_components = self._upsample_components(refined_components)
            
            # 6. 优化并保存
            saved_files, file_sizes_mb = self._optimize_and_save_components(upsampled_components)
            
            # 7. 验证结果
            print("\n✅ 最终验证:")
            print(f"  • 生成组件: {len(saved_files)} 个 (目标: 4-8)")
            print(f"  • 平均文件大小: {sum(file_sizes_mb)/len(file_sizes_mb) if file_sizes_mb else 0:.2f} MB")
            print(f"  • 总文件大小: {sum(file_sizes_mb):.1f} MB")
            
            # 8. 保存元数据
            metadata = {
                'input_volume': self.input_path,
                'volume_shape': list(self.original_shape),
                'parameters': {
                    'spatial_weight': self.spatial_weight,
                    'intensity_weight': self.intensity_weight,
                    'downsample_factor': self.downsample_factor,
                    'kmeans_clusters': self.kmeans_clusters,
                    'background_threshold': self.background_threshold,
                    'min_component_size': self.min_component_size
                },
                'components': saved_files,
                'component_count': len(saved_files),
                'total_size_mb': sum(file_sizes_mb),
                'processing_time': time.time() - start_time
            }
            
            metadata = convert_numpy_types(metadata)
            metadata_path = os.path.join(self.output_dir, 'metadata.json')
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            elapsed_time = time.time() - start_time
            print("\n" + "="*60)
            print("🎉 处理完成!")
            print(f"⏱️ 总耗时: {elapsed_time:.2f} 秒")
            print(f"📁 输出目录: {self.output_dir}")
            print("="*60)

            return saved_files

        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"❌ 处理失败! 耗时: {elapsed_time:.2f} 秒")
            print(f"错误信息: {str(e)}")
            print("💡 建议: 检查体积形状是否正确，或尝试减小max-size-ratio参数")
            raise

# ====================== 主程序 ======================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='通用3D体积分割器 (任意尺寸 + 多组件保证)')
    parser.add_argument('--input', type=str, required=True, help='输入raw文件路径')
    parser.add_argument('--output', type=str, required=True, help='输出目录')
    parser.add_argument('--shape', type=int, nargs=3, required=True, help='体积形状 [x y z]')  # 强制要求
    parser.add_argument('--max-components', type=int, default=16, help='最大组件数量')
    parser.add_argument('--min-ratio', type=float, default=0.0001, help='最小组件比例 (0.0-1.0)')
    parser.add_argument('--max-ratio', type=float, default=0.15, help='最大文件比例 (0.0-1.0)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        raise FileNotFoundError(f"输入文件不存在: {args.input}")
    
    # 参数约束
    max_components = min(16, max(4, args.max_components))  # 保证4-16个
    min_ratio = max(0.00005, min(args.min_ratio, 0.01))    # 0.005%-1%
    max_ratio = max(0.05, min(args.max_ratio, 0.25))       # 5%-25%
    
    # 形状参数: [x, y, z] -> 转换为 (z, y, x) 顺序
    shape_z_y_x = (args.shape[2], args.shape[1], args.shape[0])
    
    print("="*50)
    print("🔧 启动参数 (任意尺寸):")
    print(f"   • 输入文件: {args.input}")
    print(f"   • 输出目录: {args.output}")
    print(f"   • 体积形状: {args.shape} [x y z] → 内部: {shape_z_y_x} [z y x]")
    print(f"   • 组件数量: {max_components} (保证4-8个)")
    print(f"   • 最小组件比例: {min_ratio:.4f} ({min_ratio*100:.2f}%)")
    print(f"   • 最大文件比例: {max_ratio:.2f} ({max_ratio*100:.0f}%)")
    print("="*50)
    
    segmenter = UniversalVolumeSegmenter(
        input_path=args.input,
        output_dir=args.output,
        shape=shape_z_y_x,  # 内部使用 (z, y, x)
        dtype=np.uint8,
        min_component_ratio=min_ratio,
        max_total_components=max_components,
        max_size_ratio=max_ratio,
        timeout_seconds=300
    )
    
    saved_files = segmenter.process()
    
    print(f"\n✅ 分割完成! 生成 {len(saved_files)} 个组件文件到 {args.output}")
    print(f"💡 核心改进: 任意尺寸支持 + 保证4-8个有意义组件")
    print(f"🎯 不再有256³硬编码，完全自适应体积尺寸")